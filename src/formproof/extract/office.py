"""DOCX, XLSX, ODS, DOC."""

from __future__ import annotations

import io
import re
import struct
import zipfile
from dataclasses import dataclass
from typing import Any
from xml.etree import ElementTree as ET

import olefile

from ..types.source import BBox, BlockStyle, SourceDoc, SourcePage
from ..types.stages import ExtractInput
from .common import Builder, Seg, segment


def _cell(
    b: Builder, page: int, text: str, style: BlockStyle | None, table: int | None, row: int, col: int, rs: int, cs: int
) -> None:
    """Komórka: tekst -> `cell`, checkboxy/linie w komórce -> osobne bloki z tym samym table/row/col."""
    parts: list[str] = []
    extras = []
    for line in text.split("\n"):
        for s in segment(line):
            if s.kind == "text":
                parts.append(s.text)
            else:
                extras.append(s)
    pos: dict[str, Any] = dict(
        table=table, row=row, col=col, row_span=rs if rs > 1 else None, col_span=cs if cs > 1 else None
    )
    if parts:
        b.add(page, "cell", " ".join(parts), style=style, **pos)
    for s in extras:
        if s.kind == "checkbox":
            b.add(page, "checkbox", s.text, checked=bool(s.checked), table=table, row=row, col=col)
        else:
            b.add(page, "line", "", table=table, row=row, col=col)


# ---------------- DOCX ----------------

_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _docx_textboxes(b: Builder, d: Any, ptext: Any, pstyle: Any) -> None:
    """Pola tekstowe (np. PDF zapisany do DOCX): pozycjonowane kotwicą, kolejność = (y, x)."""
    from docx.text.paragraph import Paragraph

    boxes = d.element.body.xpath(
        './/*[local-name()="txbxContent"][not(ancestor::*[local-name()="Fallback"])]'
        '[not(ancestor::*[local-name()="txbxContent"])]'
    )
    found = []
    for i, tb in enumerate(boxes):
        anchor = tb.xpath('ancestor::*[local-name()="anchor" or local-name()="inline"][1]')
        x = y = w = h = None
        if anchor:
            a = anchor[0]

            def off(axis: str, a: Any = a) -> float | None:
                v = a.xpath(f'./*[local-name()="{axis}"]/*[local-name()="posOffset"]/text()')
                return float(v[0]) / 12700 if v else None

            x, y = off("positionH"), off("positionV")
            ext = a.xpath('./*[local-name()="extent"]')
            if ext:
                w, h = float(ext[0].get("cx", 0)) / 12700, float(ext[0].get("cy", 0)) / 12700
        found.append((y if y is not None else 0.0, x if x is not None else 0.0, i, tb, (x, y, w, h)))
    found.sort(key=lambda f: (round(f[0] / 4), f[1], f[2]))
    for _, _, _, tb, (x, y, w, h) in found:
        bbox = BBox(x=x, y=y, w=w or 0, h=h or 0) if x is not None and y is not None else None
        for pel in tb.xpath("./*[local-name()='p']"):
            p = Paragraph(pel, d)
            for line in ptext(p).split("\n"):
                if line.strip():
                    for blk in b.add_text(1, line, style=pstyle(p)):
                        blk.bbox = bbox


def extract_docx(inp: ExtractInput) -> SourceDoc:
    import docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    d = docx.Document(io.BytesIO(inp.data))
    b = Builder()
    warnings: list[str] = []
    body = d.element.body
    tno = 0

    def pstyle(p: Paragraph) -> BlockStyle | None:
        st = BlockStyle()
        name = p.style.name if p.style is not None and p.style.name else ""
        m = re.match(r"(?:Heading|Nagłówek)\s*(\d)", name)
        if m:
            st.heading = int(m.group(1))
        elif name == "Title":
            st.heading = 1
        runs = [r for r in p.runs if r.text.strip()]
        if runs:
            st.bold = all(bool(r.bold) or bool(r.style is not None and r.style.font.bold) for r in runs) or None
            st.italic = all(bool(r.italic) for r in runs) or None
            sizes = [r.font.size.pt for r in runs if r.font.size is not None]
            if sizes:
                st.font_size = sizes[0]
        if p.alignment is not None and int(p.alignment) == 1:
            st.centered = True
        if p.style is not None and p.style.font is not None and p.style.font.bold and st.bold is None:
            st.bold = True
        if st.font_size is None and p.style is not None and p.style.font.size is not None:
            st.font_size = p.style.font.size.pt
        return st if st.model_dump(exclude_none=True) else None

    def ptext(p: Paragraph) -> str:
        # w:sym (Wingdings) nie wchodzi do p.text -> dołącz jako glify; pomija pola tekstowe (osobny przebieg)
        out: list[str] = []

        def walk(el: Any) -> None:
            for ch in el:
                tag = ch.tag.rsplit("}", 1)[-1] if isinstance(ch.tag, str) else ""
                if tag in ("txbxContent", "Fallback"):
                    continue
                if tag == "t" and ch.text:
                    out.append(ch.text)
                elif tag == "tab":
                    out.append(" ")
                elif tag == "br":
                    out.append("\n")
                elif tag == "sym":
                    code = ch.get(f"{{{_W}}}char")
                    if code:
                        out.append(chr(int(code, 16)))
                walk(ch)

        walk(p._p)
        return "".join(out)

    def sdt_checkbox(p: Paragraph) -> list[str]:
        res = []
        for el in p._p.iter():
            if el.tag.endswith("}checkbox"):
                val = None
                for c in el.iter():
                    if c.tag.endswith("}checked"):
                        val = c.get(next(iter(c.attrib), ""), "0")
                res.append("☑" if val in ("1", "true") else "☐")
        return res

    def do_table(t: Table, tno: int) -> None:
        origin: dict[int, Any] = {}  # kolumna -> (blok origin, row) dla vMerge
        for ri, tr in enumerate(t._tbl.tr_lst):
            col = 0
            for tc in tr.tc_lst:
                span = tc.grid_span or 1
                if tc.vMerge == "continue":
                    blk = origin.get(col)
                    if blk is not None:
                        blk.row_span = (blk.row_span or 1) + 1
                    col += span
                    continue
                from docx.table import _Cell

                cell = _Cell(tc, t)
                text = "\n".join(ptext(p) for p in cell.paragraphs)
                n0 = len(b.blocks)
                st = pstyle(cell.paragraphs[0]) if cell.paragraphs else None
                _cell(b, 1, text, st, tno, ri, col, 1, span)
                cells = [x for x in b.blocks[n0:] if x.kind == "cell"]
                origin[col] = cells[0] if cells else None
                col += span

    for child in body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            p = Paragraph(child, d)
            text = ptext(p)
            prefix = "".join(g + " " for g in sdt_checkbox(p))
            text = (prefix + text).strip() if prefix else text
            if text.strip():
                for line in text.split("\n"):
                    b.add_text(1, line, style=pstyle(p))
        elif tag == "tbl":
            do_table(Table(child, d), tno)
            tno += 1
    _docx_textboxes(b, d, ptext, pstyle)
    if not b.blocks:
        warnings.append("DOCX: brak tekstu")
    return SourceDoc(
        filename=inp.filename, format="docx", pages=[SourcePage(page=1)], blocks=b.blocks, warnings=warnings
    )


# ---------------- arkusze: geometria siatki ----------------


@dataclass
class _GCell:
    r: int
    c: int
    rs: int
    cs: int
    text: str
    bold: bool = False
    size: float | None = None
    centered: bool = False


_MIN_LINE_PT = 25.0  # krótsze obramowanie to ramka/kreska, nie miejsce do wpisania


def _offsets(sizes: dict[int, float], default: float, n: int) -> list[float]:
    out = [0.0]
    for i in range(n):
        out.append(out[-1] + sizes.get(i, default))
    return out


def _grid_blocks(
    b: Builder,
    page: int,
    cells: list[_GCell],
    colw: dict[int, float],
    rowh: dict[int, float],
    dcol: float,
    drow: float,
    borders: set[tuple[int, int]],
) -> None:
    """Arkusz jako strona: komórki -> bloki `text` z bbox (pt) wg szerokości kolumn/wysokości wierszy.

    Formularze w arkuszach rysuje się siatką drobnych komórek; miejsca do wpisania to puste komórki
    z dolnym obramowaniem. `borders` = {(k, c)}: krawędź pod wierszem k w kolumnie c. Krawędź pod pustą
    komórką -> blok `line` (jak linia narysowana w PDF), więc INFER widzi ten sam układ co dla PDF.
    """
    if not cells:
        return
    nr = max([c.r + c.rs for c in cells] + [k + 2 for k, _ in borders]) + 1
    nc = max([c.c + c.cs for c in cells] + [c + 1 for _, c in borders]) + 1
    xs, ys = _offsets(colw, dcol, nc), _offsets(rowh, drow, nr)
    owner: dict[tuple[int, int], int] = {}
    for i, gc in enumerate(cells):
        for r in range(gc.r, gc.r + gc.rs):
            for c in range(gc.c, gc.c + gc.cs):
                owner[(r, c)] = i
    boxes: list[BBox] = []
    for gc in cells:
        x0, x1 = xs[gc.c], xs[min(gc.c + gc.cs, nc)]
        y0, y1 = ys[gc.r], ys[min(gc.r + gc.rs, nr)]
        boxes.append(BBox(x=x0, y=y0, w=x1 - x0, h=y1 - y0))
    # miejsca do wpisania: ciągi kolumn z krawędzią pod pustą komórką
    runs: list[tuple[int, int, int]] = []  # (k, c0, c1)
    for k, c in sorted(borders):
        if k < 0 or (k, c) in owner:
            continue
        if runs and runs[-1][0] == k and runs[-1][2] == c - 1:
            runs[-1] = (k, runs[-1][1], c)
        else:
            runs.append((k, c, c))
    runs = [r for r in runs if xs[r[2] + 1] - xs[r[1]] >= _MIN_LINE_PT]

    def empty_between(k0: int, k1: int, c0: int, c1: int) -> bool:
        return not any((r, c) in owner for r in range(k0 + 1, k1 + 1) for c in range(c0, c1 + 1))

    keep = []
    for k, c0, c1 in runs:
        # górna krawędź ramki nad dolną (pusta przestrzeń między) – jedno miejsce do wpisania
        lower = [
            r
            for r in runs
            if r[0] > k
            and abs(r[1] - c0) <= 1
            and abs(r[2] - c1) <= 1
            and ys[r[0] + 1] - ys[k + 1] < 30
            and empty_between(k, r[0], c0, c1)
        ]
        if not lower:
            keep.append((k, c0, c1))
    items: list[tuple[float, float, int, Any]] = []
    for i, box in enumerate(boxes):
        items.append((box.y, box.x, 0, ("cell", i)))
    for k, c0, c1 in keep:
        yb = ys[k + 1]
        band = [boxes[i] for i, gc in enumerate(cells) if gc.r <= k < gc.r + gc.rs and boxes[i].h < 60]
        if band:
            y, h = band[0].y, band[0].h
        else:
            y, h = yb - 8.0, 8.0
        items.append((y, xs[c0], 1, ("line", BBox(x=xs[c0], y=y, w=xs[c1 + 1] - xs[c0], h=h))))
    items.sort(key=lambda t: (t[0], t[1], t[2]))
    for _, _, _, (kind, ref) in items:
        if kind == "line":
            b.add(page, "line", "", bbox=ref)
            continue
        gc, box = cells[ref], boxes[ref]
        st = BlockStyle(bold=gc.bold or None, font_size=gc.size, centered=gc.centered or None)
        st_opt = st if st.model_dump(exclude_none=True) else None
        paras: list[str] = []
        for p in (x.strip() for x in gc.text.split("\n")):
            if p and paras and (paras[-1].endswith((",", "-")) or p[:1].islower()):
                paras[-1] += " " + p  # zawinięty tekst komórki ('Nazwa organu,' / 'w którym …')
            elif p:
                paras.append(p)
        paras = paras or [gc.text]
        ph = box.h / len(paras)
        cw = 0.5 * (gc.size or 10.0)
        pos: dict[str, Any] = dict(table=0, row=gc.r, col=gc.c)
        for pi, para in enumerate(paras):
            tw = min(box.w, max(len(para), 1) * cw)
            px = box.x + (box.w - tw) / 2 if gc.centered else box.x
            py = box.y + pi * ph
            n = max(len(para), 1)
            segs = segment(para)
            if any(sg.kind == "checkbox" for sg in segs) and segs[0].kind == "text" and not segs[0].text.endswith(":"):
                # znak kratki w środku zdania ('Pola wyboru oznaczaj ☐ lub ✗.') – instrukcja, nie pole wyboru
                segs = [sg for sg in segs if sg.kind != "line"] and [Seg("text", para, 0, len(para))]
            for sg in segs:
                bb = BBox(x=px + tw * sg.start / n, y=py, w=max(tw * (sg.end - sg.start) / n, 1.0), h=ph)
                if sg.kind == "text":
                    b.add(page, "text", sg.text, bbox=bb, style=st_opt, **pos)
                elif sg.kind == "checkbox":
                    b.add(page, "checkbox", sg.text, bbox=bb, checked=bool(sg.checked), **pos)
                else:
                    b.add(page, "line", "", bbox=bb, **pos)


# ---------------- XLSX ----------------


def _xlsx_border(side: Any) -> bool:
    return side is not None and side.style not in (None, "none")


def extract_xlsx(inp: ExtractInput) -> SourceDoc:
    import openpyxl
    from openpyxl.utils import column_index_from_string

    wb = openpyxl.load_workbook(io.BytesIO(inp.data), data_only=True)
    b = Builder()
    pages: list[SourcePage] = []
    for pi, ws in enumerate(wb.worksheets, start=1):
        pages.append(SourcePage(page=pi, name=ws.title))
        spans = {}
        covered = set()
        for rng in ws.merged_cells.ranges:
            spans[(rng.min_row, rng.min_col)] = (rng.max_row - rng.min_row + 1, rng.max_col - rng.min_col + 1)
            for r in range(rng.min_row, rng.max_row + 1):
                for c in range(rng.min_col, rng.max_col + 1):
                    if (r, c) != (rng.min_row, rng.min_col):
                        covered.add((r, c))
        cells: list[_GCell] = []
        borders: set[tuple[int, int]] = set()
        for row in ws.iter_rows():
            for c in row:
                bd = c.border
                if bd is not None:
                    if _xlsx_border(bd.bottom):
                        borders.add((c.row - 1, c.column - 1))
                    if _xlsx_border(bd.top):
                        borders.add((c.row - 2, c.column - 1))
                if c.value is None or (c.row, c.column) in covered:
                    continue
                text = str(c.value).strip()
                if not text:
                    continue
                rs, cs = spans.get((c.row, c.column), (1, 1))
                f = c.font
                al = c.alignment
                cells.append(
                    _GCell(
                        c.row - 1,
                        c.column - 1,
                        rs,
                        cs,
                        text,
                        bold=bool(f is not None and f.b),
                        size=float(f.sz) if f is not None and f.sz else None,
                        centered=bool(al is not None and al.horizontal in ("center", "centerContinuous")),
                    )
                )
        dcol = float(ws.sheet_format.defaultColWidth or ws.sheet_format.baseColWidth or 8.43) * 5.6
        drow = float(ws.sheet_format.defaultRowHeight or 15.0)
        colw: dict[int, float] = {}
        for k, dim in ws.column_dimensions.items():
            if dim.width:
                lo = dim.min or column_index_from_string(k)
                hi = dim.max or lo
                for ci in range(lo, min(hi, lo + 512) + 1):
                    colw[ci - 1] = float(dim.width) * 5.6
        rowh = {k - 1: float(dim.height) for k, dim in ws.row_dimensions.items() if dim.height}
        _grid_blocks(b, pi, cells, colw, rowh, dcol, drow, borders)
    return SourceDoc(filename=inp.filename, format="xlsx", pages=pages, blocks=b.blocks)


# ---------------- ODS ----------------

_NS = {
    "table": "urn:oasis:names:tc:opendocument:xmlns:table:1.0",
    "text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0",
    "style": "urn:oasis:names:tc:opendocument:xmlns:style:1.0",
    "fo": "urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0",
}
_UNIT_PT = {"pt": 1.0, "cm": 28.3465, "mm": 2.83465, "in": 72.0, "pc": 12.0, "px": 0.75}


def _q(prefix: str, name: str) -> str:
    return f"{{{_NS[prefix]}}}{name}"


def _len_pt(v: str | None) -> float | None:
    m = re.match(r"^\s*([\d.]+)\s*([a-z]+)", v or "")
    if not m or m.group(2) not in _UNIT_PT:
        return None
    return float(m.group(1)) * _UNIT_PT[m.group(2)]


def _ods_walk(e: ET.Element, buf: list[str]) -> None:
    if e.text:
        buf.append(e.text)
    for ch in e:
        if ch.tag == _q("text", "s"):
            buf.append(" " * int(ch.get(_q("text", "c"), "1")))
        elif ch.tag == _q("text", "tab"):
            buf.append(" ")
        else:
            _ods_walk(ch, buf)
        if ch.tail:
            buf.append(ch.tail)


def _ods_text(cell: ET.Element) -> str:
    paras = []
    for p in cell.findall(_q("text", "p")):
        buf: list[str] = []
        _ods_walk(p, buf)
        paras.append("".join(buf))
    return "\n".join(paras).strip()


@dataclass
class _OdsStyle:
    bottom: bool = False
    top: bool = False
    bold: bool = False
    size: float | None = None
    centered: bool = False
    width: float | None = None
    height: float | None = None


def _ods_styles(*roots: ET.Element) -> dict[str, _OdsStyle]:
    def has_border(v: str | None) -> bool:
        if not v:
            return False
        return v.strip() != "none" and not v.strip().startswith("0pt") and "none" not in v.split()

    out: dict[str, _OdsStyle] = {}
    for root in roots:
        for st in root.iter(_q("style", "style")):
            name = st.get(_q("style", "name"))
            if not name:
                continue
            s = _OdsStyle()
            parent = out.get(st.get(_q("style", "parent-style-name")) or "")
            if parent:
                s = _OdsStyle(**parent.__dict__)
                s.width = s.height = None
            cp = st.find(_q("style", "table-cell-properties"))
            if cp is not None:
                allb = cp.get(_q("fo", "border"))
                bb, tb = cp.get(_q("fo", "border-bottom")) or allb, cp.get(_q("fo", "border-top")) or allb
                s.bottom, s.top = has_border(bb), has_border(tb)
            tp = st.find(_q("style", "text-properties"))
            if tp is not None:
                if tp.get(_q("fo", "font-weight")) in ("bold", "600", "700", "800", "900"):
                    s.bold = True
                s.size = _len_pt(tp.get(_q("fo", "font-size"))) or s.size
            pp = st.find(_q("style", "paragraph-properties"))
            if pp is not None and pp.get(_q("fo", "text-align")) == "center":
                s.centered = True
            colp = st.find(_q("style", "table-column-properties"))
            if colp is not None:
                s.width = _len_pt(colp.get(_q("style", "column-width")))
            rowp = st.find(_q("style", "table-row-properties"))
            if rowp is not None:
                s.height = _len_pt(rowp.get(_q("style", "row-height")))
            out[name] = s
    return out


def extract_ods(inp: ExtractInput) -> SourceDoc:
    with zipfile.ZipFile(io.BytesIO(inp.data)) as z:
        root = ET.fromstring(z.read("content.xml"))  # noqa: S314 (expat chroni przed bomb entity; brak zewn. encji)
        sroot = ET.fromstring(z.read("styles.xml")) if "styles.xml" in z.namelist() else None  # noqa: S314
    styles = _ods_styles(*([sroot] if sroot is not None else []), root)
    nost = _OdsStyle()
    b = Builder()
    pages: list[SourcePage] = []
    tables = list(root.iter(_q("table", "table")))
    for pi, t in enumerate(tables, start=1):
        pages.append(SourcePage(page=pi, name=t.get(_q("table", "name"))))
        colw: dict[int, float] = {}
        col_cell_style: dict[int, str] = {}
        ci = 0
        for col in t.iter(_q("table", "table-column")):
            rep = int(col.get(_q("table", "number-columns-repeated"), "1"))
            w = styles.get(col.get(_q("table", "style-name")) or "", nost).width
            dcs = col.get(_q("table", "default-cell-style-name")) or ""
            for k in range(ci, ci + min(rep, 1024)):
                if w:
                    colw[k] = w
                col_cell_style[k] = dcs
            ci += rep
        rowh: dict[int, float] = {}
        cells: list[_GCell] = []
        borders: set[tuple[int, int]] = set()
        rows = list(t.iter(_q("table", "table-row")))
        ri = 0
        last_used = max(
            (k for k, r in enumerate(rows) if any(_ods_text(c) for c in r.iter(_q("table", "table-cell")))),
            default=-1,
        )
        for k, r in enumerate(rows):
            if k > last_used + 5:
                break
            rrep = min(int(r.get(_q("table", "number-rows-repeated"), "1")), 64)
            h = styles.get(r.get(_q("table", "style-name")) or "", nost).height
            for rr in range(ri, ri + rrep):
                if h:
                    rowh[rr] = h
            ci = 0
            for c in r:
                if c.tag not in (_q("table", "table-cell"), _q("table", "covered-table-cell")):
                    continue
                crep = int(c.get(_q("table", "number-columns-repeated"), "1"))
                sname = c.get(_q("table", "style-name")) or col_cell_style.get(ci, "")
                cst = styles.get(sname, nost)
                if crep <= 256 and (cst.bottom or cst.top):
                    rs0 = int(c.get(_q("table", "number-rows-spanned"), "1"))
                    cs0 = int(c.get(_q("table", "number-columns-spanned"), "1"))
                    for rr in range(ri, ri + rrep):
                        for cc in range(ci, ci + max(crep, cs0)):
                            if cst.bottom:
                                borders.add((rr + rs0 - 1, cc))
                            if cst.top:
                                borders.add((rr - 1, cc))
                if c.tag == _q("table", "table-cell"):
                    text = _ods_text(c)
                    if text:
                        cs = int(c.get(_q("table", "number-columns-spanned"), "1"))
                        rs = int(c.get(_q("table", "number-rows-spanned"), "1"))
                        bold = cst.bold or any(
                            styles.get(sp.get(_q("text", "style-name")) or "", nost).bold
                            for sp in c.iter(_q("text", "span"))
                        )
                        cells.append(_GCell(ri, ci, rs, cs, text, bold=bold, size=cst.size, centered=cst.centered))
                ci += crep
            ri += rrep
        dcol = styles.get("Default", nost).width or 64 * 0.75
        drow = styles.get("Default", nost).height or 12.8 * 1.33
        _grid_blocks(b, pi, cells, colw, rowh, dcol, drow, borders)
    return SourceDoc(filename=inp.filename, format="ods", pages=pages, blocks=b.blocks)


# ---------------- DOC ----------------


def _doc_piece_text(word: bytes, table: bytes) -> str | None:
    try:
        flags = struct.unpack_from("<H", word, 0x0A)[0]
        _ = flags
        ccp_text = struct.unpack_from("<i", word, 0x4C)[0]
        fc_clx, lcb_clx = struct.unpack_from("<II", word, 0x1A2)
        clx = table[fc_clx : fc_clx + lcb_clx]
        i = 0
        while i < len(clx) and clx[i] == 1:
            i += 3 + struct.unpack_from("<H", clx, i + 1)[0]
        if clx[i] != 2:
            return None
        lcb = struct.unpack_from("<I", clx, i + 1)[0]
        plc = clx[i + 5 : i + 5 + lcb]
        n = (lcb - 4) // 12
        cps = struct.unpack_from(f"<{n + 1}I", plc, 0)
        out = []
        for k in range(n):
            fc = struct.unpack_from("<I", plc, 4 * (n + 1) + 8 * k + 2)[0]
            length = cps[k + 1] - cps[k]
            if fc & 0x40000000:
                off = (fc & ~0x40000000) // 2
                out.append(word[off : off + length].decode("cp1250", errors="replace"))
            else:
                out.append(word[fc : fc + 2 * length].decode("utf-16le", errors="replace"))
        full = "".join(out)
        if ccp_text <= 0:
            return full
        ccps = struct.unpack_from("<7i", word, 0x4C)  # text, ftn, hdd, mcr, atn, edn, txbx
        start = sum(ccps[:6])
        return full[:ccp_text] + "\r" + full[start : start + max(ccps[6], 0)]
    except struct.error, IndexError:
        return None


def _doc_heuristic(word: bytes) -> str:
    chunks = re.findall(rb"(?:[\x20-\x7e\r\t]\x00|[\x00-\xff]\x01|[\x00-\xff]\x00){6,}", word)
    txt = "".join(c.decode("utf-16le", errors="ignore") for c in chunks)
    if len(txt.strip()) < 50:
        txt = word.decode("cp1250", errors="ignore")
    return txt


def extract_doc(inp: ExtractInput) -> SourceDoc:
    warnings = ["DOC: tylko tekst"]
    ole = olefile.OleFileIO(io.BytesIO(inp.data))
    try:
        word = ole.openstream("WordDocument").read()
        flags = struct.unpack_from("<H", word, 0x0A)[0]
        tname = "1Table" if flags & 0x0200 else "0Table"
        table = ole.openstream(tname).read() if ole.exists(tname) else b""
    finally:
        ole.close()
    text = _doc_piece_text(word, table)
    if not text or len(text.strip()) < 10:
        text = _doc_heuristic(word)
        warnings.append("DOC: heurystyczne wyciąganie tekstu")
    text = re.sub(r"[\x00-\x06\x08\x0e-\x1f]", "", text)
    text = text.replace("\x07", "\r").replace("\x0b", "\r").replace("\x0c", "\r")
    b = Builder()
    for para in re.split(r"\r+", text):
        if para.strip():
            b.add_text(1, para.strip())
    return SourceDoc(
        filename=inp.filename, format="doc", pages=[SourcePage(page=1)], blocks=b.blocks, warnings=warnings
    )
