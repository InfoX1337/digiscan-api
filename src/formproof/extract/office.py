"""DOCX, XLSX, ODS, DOC."""

from __future__ import annotations

import io
import re
import struct
import zipfile
from typing import Any
from xml.etree import ElementTree as ET

import olefile

from ..types.source import BBox, BlockStyle, SourceDoc, SourcePage
from ..types.stages import ExtractInput
from .common import Builder, segment


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


# ---------------- XLSX ----------------


def extract_xlsx(inp: ExtractInput) -> SourceDoc:
    import openpyxl

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
        for row in ws.iter_rows():
            for c in row:
                if c.value is None or (c.row, c.column) in covered:
                    continue
                text = str(c.value).strip()
                if not text:
                    continue
                rs, cs = spans.get((c.row, c.column), (1, 1))
                st = BlockStyle(bold=True) if c.font is not None and c.font.b else None
                _cell(b, pi, text, st, 0, c.row - 1, c.column - 1, rs, cs)
    return SourceDoc(filename=inp.filename, format="xlsx", pages=pages, blocks=b.blocks)


# ---------------- ODS ----------------

_NS = {
    "table": "urn:oasis:names:tc:opendocument:xmlns:table:1.0",
    "text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0",
}


def _q(prefix: str, name: str) -> str:
    return f"{{{_NS[prefix]}}}{name}"


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


def extract_ods(inp: ExtractInput) -> SourceDoc:
    with zipfile.ZipFile(io.BytesIO(inp.data)) as z:
        root = ET.fromstring(z.read("content.xml"))  # noqa: S314 (expat chroni przed bomb entity; brak zewn. encji)
    b = Builder()
    pages: list[SourcePage] = []
    tables = list(root.iter(_q("table", "table")))
    for pi, t in enumerate(tables, start=1):
        pages.append(SourcePage(page=pi, name=t.get(_q("table", "name"))))
        rows = [r for r in t.iter(_q("table", "table-row"))]
        ri = 0
        for r in rows:
            rrep = int(r.get(_q("table", "number-rows-repeated"), "1"))
            ci = 0
            any_cell = False
            for c in r:
                if c.tag not in (_q("table", "table-cell"), _q("table", "covered-table-cell")):
                    continue
                crep = int(c.get(_q("table", "number-columns-repeated"), "1"))
                if c.tag == _q("table", "table-cell"):
                    text = _ods_text(c)
                    if text:
                        any_cell = True
                        cs = int(c.get(_q("table", "number-columns-spanned"), "1"))
                        rs = int(c.get(_q("table", "number-rows-spanned"), "1"))
                        _cell(b, pi, text, None, 0, ri, ci, rs, cs)
                ci += crep
            ri += rrep if not any_cell else 1
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
