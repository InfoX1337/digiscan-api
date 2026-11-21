"""PDF (pdfplumber): tekst, tabele, checkboxy, linie do wpisania; brak warstwy tekstu -> OCR."""

from __future__ import annotations

import io
import statistics
from dataclasses import dataclass
from typing import Any

import pdfplumber

from ..types.source import BBox, BlockKind, BlockStyle, SourceDoc, SourcePage
from ..types.stages import ExtractInput
from .common import Builder, expired, segment

OCR_SCALE = 2.0
MIN_CHARS_FOR_TEXT_PAGE = 15

Char = dict[str, Any]


@dataclass
class Item:
    kind: BlockKind
    text: str
    x0: float
    top: float
    x1: float
    bottom: float
    style: BlockStyle | None = None
    checked: bool | None = None

    @property
    def bbox(self) -> BBox:
        return BBox(x=self.x0, y=self.top, w=self.x1 - self.x0, h=self.bottom - self.top)


def _style(chars: list[Char]) -> BlockStyle | None:
    real = [c for c in chars if c.get("text", "").strip() and "fontname" in c]
    if not real:
        return None
    names = [str(c["fontname"]).lower() for c in real]
    bold = sum(any(k in n for k in ("bold", "black", "heavy", "demi")) for n in names) > len(real) / 2
    ital = sum(any(k in n for k in ("italic", "oblique")) for n in names) > len(real) / 2
    size = round(statistics.median(float(c["size"]) for c in real), 1)
    return BlockStyle(bold=bold or None, italic=ital or None, font_size=size)


def _cluster_lines(chars: list[Char]) -> list[list[Char]]:
    """Grupuje znaki w linie wizualne, a linie dzieli na kolumny przy dużych przerwach."""
    chars = sorted(chars, key=lambda c: ((c["top"] + c["bottom"]) / 2, c["x0"]))
    rows: list[list[Char]] = []
    for c in chars:
        mid = (c["top"] + c["bottom"]) / 2
        h = max(c["bottom"] - c["top"], 1.0)
        if rows:
            last = rows[-1]
            lmid = statistics.fmean((k["top"] + k["bottom"]) / 2 for k in last)
            if abs(mid - lmid) <= 0.45 * h:
                last.append(c)
                continue
        rows.append([c])
    out: list[list[Char]] = []
    for row in rows:
        row.sort(key=lambda c: c["x0"])
        cur = [row[0]]
        for c in row[1:]:
            size = max(float(c.get("size") or 10), 4.0)
            if c["x0"] - cur[-1]["x1"] > 2.2 * size and c.get("text", "").strip():
                out.append(cur)
                cur = [c]
            else:
                cur.append(c)
        out.append(cur)
    return out


def _line_items(chars: list[Char]) -> list[Item]:
    items: list[Item] = []
    for line in _cluster_lines(chars):
        text_chars: list[str] = []
        refs: list[Char | None] = []
        prev: Char | None = None
        for c in line:
            if prev is not None and c["text"] != " " and prev["text"] != " ":
                gap = c["x0"] - prev["x1"]
                if gap > 0.25 * max(float(c.get("size") or 10), 4.0):
                    text_chars.append(" ")
                    refs.append(None)
            text_chars.append(c["text"])
            refs.append(c)
            prev = c
        text = "".join(text_chars)
        for s in segment(text):
            span = [r for r in refs[s.start : s.end] if r is not None]
            if not span:
                continue
            x0 = min(r["x0"] for r in span)
            x1 = max(r["x1"] for r in span)
            top = min(r["top"] for r in span)
            bottom = max(r["bottom"] for r in span)
            if s.kind == "text":
                items.append(Item("text", s.text, x0, top, x1, bottom, _style(span)))
            elif s.kind == "checkbox":
                items.append(Item("checkbox", s.text, x0, top, x1, bottom, _style(span), bool(s.checked)))
            else:
                items.append(Item("line", "", x0, top, x1, bottom))
    return items


def _square_rects(rects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for r in rects:
        w, h = r["x1"] - r["x0"], r["bottom"] - r["top"]
        if 5 <= w <= 22 and 5 <= h <= 22 and abs(w - h) <= 5:
            out.append(r)
    return out


def _edge_squares(page: Any) -> list[dict[str, Any]]:
    """Kwadraty narysowane czterema liniami (bez prostokąta): małe pola wyboru / komórki znakowe."""
    hs = [e for e in page.edges if e["orientation"] == "h" and 5 <= e["x1"] - e["x0"] <= 20]
    vs = [e for e in page.edges if e["orientation"] == "v" and 5 <= e["bottom"] - e["top"] <= 22]
    out: list[dict[str, Any]] = []
    seen: set[tuple[int, int, int, int]] = set()
    for a in hs:
        for b in hs:
            if b["top"] <= a["top"] + 4:
                continue
            side = b["top"] - a["top"]
            if side > 22 or abs(a["x0"] - b["x0"]) > 1.5 or abs(a["x1"] - b["x1"]) > 1.5:
                continue
            w = a["x1"] - a["x0"]
            if abs(w - side) > 5:
                continue
            ok_l = any(
                abs(v["x0"] - a["x0"]) <= 1.5 and v["top"] <= a["top"] + 1.5 and v["bottom"] >= b["top"] - 1.5
                for v in vs
            )
            ok_r = any(
                abs(v["x0"] - a["x1"]) <= 1.5 and v["top"] <= a["top"] + 1.5 and v["bottom"] >= b["top"] - 1.5
                for v in vs
            )
            key = (round(a["x0"]), round(a["top"]), round(w), round(side))
            if ok_l and ok_r and key not in seen:
                seen.add(key)
                out.append({"x0": a["x0"], "x1": a["x1"], "top": a["top"], "bottom": b["top"], "fill": False})
    return out


def _is_dark_fill(r: dict[str, Any]) -> bool:
    if not r.get("fill"):
        return False
    col = r.get("non_stroking_color")
    if col is None:
        return False
    vals = col if isinstance(col, (list, tuple)) else [col]
    try:
        return all(float(v) < 0.4 for v in vals) if len(vals) != 4 else float(vals[3]) > 0.6
    except TypeError, ValueError:
        return False


def _box_chars(squares: list[dict[str, Any]]) -> tuple[list[Char], list[Item]]:
    """Kwadraty -> pseudo-znaki checkboxów; rzędy >=4 przylegających kwadratów -> pole znakowe (line)."""
    sq = sorted(squares, key=lambda r: (round(r["top"] / 2), r["x0"]))
    used: set[int] = set()
    combs: list[Item] = []
    i = 0
    while i < len(sq):
        group = [i]
        while (
            group
            and group[-1] + 1 < len(sq)
            and abs(sq[group[-1] + 1]["top"] - sq[i]["top"]) <= 1.5
            and abs((sq[group[-1] + 1]["x1"] - sq[group[-1] + 1]["x0"]) - (sq[i]["x1"] - sq[i]["x0"])) <= 1.5
            and -1 <= sq[group[-1] + 1]["x0"] - sq[group[-1]]["x1"] <= 4
        ):
            group.append(group[-1] + 1)
        if len(group) >= 4:
            used.update(group)
            g = [sq[k] for k in group]
            combs.append(
                Item(
                    "line",
                    "",
                    min(r["x0"] for r in g),
                    min(r["top"] for r in g),
                    max(r["x1"] for r in g),
                    max(r["bottom"] for r in g),
                )
            )
        i = group[-1] + 1
    chars: list[Char] = []
    for k, r in enumerate(sq):
        if k in used:
            continue
        chars.append(
            {
                "text": "☑" if _is_dark_fill(r) else "☐",
                "x0": r["x0"],
                "x1": r["x1"],
                "top": r["top"],
                "bottom": r["bottom"],
                "size": r["bottom"] - r["top"],
            }
        )
    return chars, combs


def _edges(vals: list[float], tol: float = 2.0) -> list[float]:
    out: list[float] = []
    for v in sorted(vals):
        if not out or v - out[-1] > tol:
            out.append(v)
    return out


def _idx(edges: list[float], v: float) -> int:
    return min(range(len(edges)), key=lambda i: abs(edges[i] - v))


def _in(bbox: tuple[float, float, float, float], x: float, y: float, pad: float = 0.5) -> bool:
    return bbox[0] - pad <= x <= bbox[2] + pad and bbox[1] - pad <= y <= bbox[3] + pad


def _cx(c: dict[str, Any]) -> tuple[float, float]:
    return (c["x0"] + c["x1"]) / 2, (c["top"] + c["bottom"]) / 2


def _rules(page: Any, tables_bbox: list[tuple[float, float, float, float]], lines: list[Item]) -> list[Item]:
    """Poziome linie/cienkie prostokąty poza tabelami, które nie są podkreśleniem tekstu."""
    cand: list[tuple[float, float, float]] = []
    for ln in page.lines:
        if abs(ln["top"] - ln["bottom"]) < 1.5 and ln["x1"] - ln["x0"] >= 30:
            cand.append((ln["x0"], ln["x1"], (ln["top"] + ln["bottom"]) / 2))
    for r in page.rects:
        if r["bottom"] - r["top"] <= 1.6 and r["x1"] - r["x0"] >= 30:
            cand.append((r["x0"], r["x1"], (r["top"] + r["bottom"]) / 2))
    out: list[Item] = []
    seen: set[tuple[int, int, int]] = set()
    for x0, x1, y in cand:
        if any(_in(tb, (x0 + x1) / 2, y, 2) for tb in tables_bbox):
            continue
        key = (round(x0 / 3), round(x1 / 3), round(y / 2))
        if key in seen:
            continue
        seen.add(key)
        # podkreślenie istniejącego tekstu (tekst tuż nad linią) – pomijamy
        underline = False
        for it in lines:
            if it.kind != "text":
                continue
            ov = min(x1, it.x1) - max(x0, it.x0)
            if ov > 0.5 * (it.x1 - it.x0) and -1.5 <= y - it.bottom <= 2.5:
                underline = True
                break
        if underline:
            continue
        out.append(Item("line", "", x0, y - 8, x1, y))
    return out


def _page_items(page: Any, warnings: list[str]) -> list[tuple[float, float, float, list[Item], int | None]]:
    """Zwraca jednostki kolejności: (y, x, h, items, table_no); items dla tabeli to cell-bloki w kolejności."""
    units: list[tuple[float, float, float, list[Item], int | None]] = []
    chars = [c for c in page.chars if c.get("upright", True) and c["text"] != "\n"]
    # deduplikacja nakładających się znaków
    seen: set[tuple[str, int, int]] = set()
    uniq: list[Char] = []
    for c in chars:
        k = (c["text"], round(c["x0"]), round(c["top"]))
        if k not in seen:
            seen.add(k)
            uniq.append(c)
    chars = uniq
    squares = _square_rects(page.rects)
    for es in _edge_squares(page):
        cx, cy = _cx(es)
        if not any(_in((r["x0"], r["top"], r["x1"], r["bottom"]), cx, cy, 1.0) for r in squares):
            squares.append(es)

    tables = []
    try:
        tables = page.find_tables()
    except Exception as e:
        warnings.append(f"tabele: {e}")
    tbboxes = [tuple(t.bbox) for t in tables]

    # tabele
    consumed_chars: set[int] = set()
    consumed_sq: set[int] = set()
    cell_units: list[tuple[int, Any]] = []
    comb_items: list[Item] = []
    tbboxes_skip: set[int] = set()
    for ti, t in enumerate(tables):
        cells = [tuple(c) for row in t.rows for c in row.cells if c is not None]
        cells = list(dict.fromkeys(cells))
        if not cells:
            continue
        if all(c[2] - c[0] <= 25 and c[3] - c[1] <= 25 for c in cells):
            # tabela z samych małych komórek = pole znakowe (np. PESEL, kod pocztowy)
            tb = tuple(t.bbox)
            for ch in chars:
                if _in(tb, *_cx(ch), pad=0):
                    consumed_chars.add(id(ch))
            for r in squares:
                if _in(tb, *_cx(r), pad=1):
                    consumed_sq.add(id(r))
            comb_items.append(Item("line", "", tb[0], tb[1], tb[2], tb[3]))
            tbboxes_skip.add(ti)
            continue
        xe = _edges([v for c in cells for v in (c[0], c[2])])
        ye = _edges([v for c in cells for v in (c[1], c[3])])
        recs = []
        for c in cells:
            cc = [ch for ch in chars if _in(c, *_cx(ch), pad=0)]
            for ch in cc:
                consumed_chars.add(id(ch))
            cs = [
                r
                for r in squares
                if _in(c, *_cx(r), pad=0)
                and not (abs(r["x0"] - c[0]) < 2.5 and abs(r["x1"] - c[2]) < 2.5 and abs(r["top"] - c[1]) < 2.5)
            ]
            for r in cs:
                consumed_sq.add(id(r))
            pc, combs = _box_chars(cs)
            its = _line_items(cc + pc) + combs
            recs.append((c, its))
        cell_units.append((ti, (t, xe, ye, recs)))

    # wolny tekst
    free_chars = [c for c in chars if id(c) not in consumed_chars]
    free_sq = [r for r in squares if id(r) not in consumed_sq and not any(_in(tb, *_cx(r)) for tb in tbboxes)]
    pc, combs = _box_chars(free_sq)
    free_items = _line_items(free_chars + pc) + combs + comb_items
    free_items += _rules(page, tbboxes, free_items)
    for it in free_items:
        units.append(((it.top + it.bottom) / 2, it.x0, max(it.bottom - it.top, 1.0), [it], None))

    for ti, (_t, xe, ye, recs) in cell_units:
        flat: list[tuple[int, int, int, int, Item, tuple[float, ...]]] = []
        for c, its in recs:
            col, row = _idx(xe, c[0]), _idx(ye, c[1])
            cspan, rspan = _idx(xe, c[2]) - col, _idx(ye, c[3]) - row
            texts = [i for i in its if i.kind == "text"]
            if texts:
                st = texts[0].style
                joined = " ".join(i.text for i in texts)
                cell = Item("text", joined, c[0], c[1], c[2], c[3], st)
                flat.append((row, col, max(rspan, 1), max(cspan, 1), cell, c))
            for i in its:
                if i.kind != "text":
                    flat.append((row, col, 1, 1, i, c))
        flat.sort(key=lambda f: (f[0], f[1], f[4].kind != "text", f[4].top, f[4].x0))
        t0 = tbboxes[ti]
        units.append((t0[1] + 0.5, t0[0], 1.0, [], ti))
        units[-1] = (units[-1][0], units[-1][1], units[-1][2], [_wrap(f) for f in flat], ti)
    return units


@dataclass
class CellItem(Item):
    table: int | None = None
    row: int = 0
    col: int = 0
    rs: int = 1
    cs: int = 1


def _wrap(f: tuple[int, int, int, int, Item, tuple[float, ...]]) -> Item:
    row, col, rs, cs, it, _ = f
    ci = CellItem(it.kind, it.text, it.x0, it.top, it.x1, it.bottom, it.style, it.checked)
    ci.row, ci.col, ci.rs, ci.cs = row, col, rs, cs
    if it.kind == "text":
        ci.kind = "cell"
    return ci


def _order(units: list[tuple[float, float, float, list[Item], int | None]]) -> list[tuple[Item, int | None]]:
    units = sorted(units, key=lambda u: (u[0], u[1]))
    groups: list[list[tuple[float, float, float, list[Item], int | None]]] = []
    for u in units:
        if (
            groups
            and u[4] is None
            and groups[-1][0][4] is None
            and abs(u[0] - groups[-1][0][0]) <= 0.5 * groups[-1][0][2]
        ):
            groups[-1].append(u)
        else:
            groups.append([u])
    out: list[tuple[Item, int | None]] = []
    for g in groups:
        g.sort(key=lambda u: u[1])
        for u in g:
            for it in u[3]:
                out.append((it, u[4]))
    return out


def extract_pdf(inp: ExtractInput) -> SourceDoc:
    warnings: list[str] = []
    b = Builder()
    pages: list[SourcePage] = []
    ocr_used = False
    ocr_pages = 0
    lang: str | None = None
    lang_tried = False
    pdfium_doc: Any = None
    with pdfplumber.open(io.BytesIO(inp.data)) as pdf:
        for pi, page in enumerate(pdf.pages, start=1):
            pages.append(SourcePage(page=pi, width=float(page.width), height=float(page.height)))
            if expired(inp.deadline):
                warnings.append(f"przekroczono limit czasu, przerwano na stronie {pi}")
                break
            nchars = sum(1 for c in page.chars if c["text"].strip())
            if nchars < MIN_CHARS_FOR_TEXT_PAGE:
                if ocr_pages >= inp.max_ocr_pages:
                    warnings.append(f"strona {pi}: brak tekstu, pominięto OCR (limit {inp.max_ocr_pages} stron)")
                    continue
                from . import ocr

                if not lang_tried:
                    lang_tried = True
                    lang = ocr.pick_lang(warnings)
                if lang is None:
                    continue
                if pdfium_doc is None:
                    import pypdfium2

                    pdfium_doc = pypdfium2.PdfDocument(inp.data)
                img = pdfium_doc[pi - 1].render(scale=OCR_SCALE).to_pil().convert("RGB")
                ocr.add_ocr_lines(b, pi, ocr.ocr_lines(img, lang, scale=OCR_SCALE))
                ocr_pages += 1
                ocr_used = True
                continue
            for it, tno in _order(_page_items(page, warnings)):
                kw: dict[str, Any] = {}
                if isinstance(it, CellItem):
                    kw = dict(
                        table=tno,
                        row=it.row,
                        col=it.col,
                        row_span=it.rs if it.rs > 1 else None,
                        col_span=it.cs if it.cs > 1 else None,
                    )
                if it.kind == "checkbox":
                    kw["checked"] = bool(it.checked)
                b.add(pi, it.kind, it.text, it.bbox, it.style, **kw)
    if pdfium_doc is not None:
        pdfium_doc.close()
    return SourceDoc(filename=inp.filename, format="pdf", ocr=ocr_used, pages=pages, blocks=b.blocks, warnings=warnings)
