"""Normalizacja bloków SourceDoc do linii (kolejność czytania) + pomocnicze dopasowania tekstu."""

from __future__ import annotations

import re
import statistics
import unicodedata
from dataclasses import dataclass, field

from ..types.source import BBox, SourceBlock, SourceDoc

PLACEHOLDER = re.compile(r"[.…_]{3,}|…+|_{2,}")
# podpis pod miejscem do wpisania: '(imię i nazwisko)' albo '/ imię i nazwisko /'
PAREN_HINT = re.compile(r"^(?:\((?P<p>[^()]{2,120})\)|/\s*(?P<s>[^/()]{2,60}?)\s*/)$")
_PRIVATE_GLYPH = re.compile(r"^[\ue000-\uf8ff\u24d8\u2139\u2022\u25aa\u25cf\u2023\u2043]+\s*")


def hint_text(m: re.Match[str]) -> str:
    return m.group("p") or m.group("s")


FOOTNOTE_MARK = re.compile(r"^\d{1,2}\s?\)$")


def fold(s: str) -> str:
    """Małe litery bez polskich znaków (do dopasowań regex)."""
    s = s.replace("ł", "l").replace("Ł", "L")
    return "".join(c for c in unicodedata.normalize("NFKD", s.lower()) if not unicodedata.combining(c))


def clean(s: str) -> str:
    s = PLACEHOLDER.sub(" ", s).replace("`", " ")
    s = _PRIVATE_GLYPH.sub("", s.strip())  # znak symbolu (Wingdings, ⓘ, punktor) na początku
    s = re.sub(r"\s+", " ", s).strip(" :;,-–*\t")
    return s


@dataclass
class Line:
    page: int
    text: str
    block_ids: list[str]
    bbox: BBox | None = None
    font: float | None = None
    bold: bool = False
    heading: int | None = None
    centered: bool = False
    conf: float = 1.0
    kind: str = "text"  # text | cell | checkbox | line
    checked: bool | None = None
    table: int | None = None
    row: int | None = None
    col: int | None = None
    consumed: bool = False
    tags: set[str] = field(default_factory=set)

    @property
    def y(self) -> float:
        return self.bbox.y if self.bbox else 0.0

    @property
    def x(self) -> float:
        return self.bbox.x if self.bbox else 0.0

    @property
    def has_placeholder(self) -> bool:
        return self.kind == "line" or "input" in self.tags or bool(PLACEHOLDER.search(self.text))

    @property
    def only_placeholder(self) -> bool:
        return self.has_placeholder and not clean(self.text)


def _merge(a: SourceBlock, b: SourceBlock) -> bool:
    if a.page != b.page or not a.bbox or not b.bbox or "checkbox" in (a.kind, b.kind) or "cell" in (a.kind, b.kind):
        return False
    h = max(a.bbox.h, b.bbox.h, 1.0)
    same_row = abs((a.bbox.y + a.bbox.h / 2) - (b.bbox.y + b.bbox.h / 2)) < 0.5 * h
    gap = b.bbox.x - (a.bbox.x + a.bbox.w)
    return same_row and -h < gap < 2.5 * h


COL_GAP = re.compile(r"\s{6,}")
LINE_MARK = "____"  # znacznik miejsca do wpisania (blok 'line') w scalonej linii


def _split_columns(b: SourceBlock) -> list[SourceBlock]:
    """Blok z dwiema kolumnami tekstu ('(imię i nazwisko)      Wójt', 'Wnioskodawca: Adresat:') -> osobne bloki."""
    if b.kind != "text" or not b.text.strip():
        return [b]
    raw = b.text.strip()
    parts = [p for p in COL_GAP.split(raw) if p.strip()]
    if len(parts) == 1:
        m = re.fullmatch(r"([^:]{2,40}:)\s+([^:]{2,40}:)", raw) or re.fullmatch(
            r"(\([^()]{2,120}\))\s+([A-ZĄĆĘŁŃÓŚŹŻ][^()]{1,80})", raw
        )
        if not m:
            return [b]
        parts = [m.group(1), m.group(2)]
    out: list[SourceBlock] = []
    pos = 0
    n = max(len(raw), 1)
    for p in parts:
        start = raw.index(p, pos)
        pos = start + len(p)
        bb = None
        if b.bbox:
            bb = BBox(x=b.bbox.x + b.bbox.w * start / n, y=b.bbox.y, w=b.bbox.w * len(p) / n, h=b.bbox.h)
        out.append(b.model_copy(update={"text": p, "bbox": bb}))  # to samo id – źródło w raporcie wskazuje blok
    return out


_LEADER_CHARS = set("ceosuvartnilm")


def _is_leader(tok: str) -> bool:
    """Kropki wykropkowania odczytane przez OCR ('cece', 'eee', 'ceceueveseee', '0.6...')."""
    if len(tok) < 2:
        return False
    dots = sum(tok.count(c) for c in ".…")
    if dots >= 0.5 * len(tok) and len(tok) >= 3:
        return True
    t = tok.strip(".,:;…'`-").lower()
    return len(t) >= 2 and set(t) <= _LEADER_CHARS and (t.count("e") + t.count("c")) >= 0.6 * len(t)


def _is_weak_leader(tok: str) -> bool:
    t = tok.strip(".,:;…'`-").lower()
    return 0 < len(t) <= 9 and set(t) <= _LEADER_CHARS


def denoise_ocr(text: str) -> str:
    """Ciąg śmieci OCR (co najmniej jeden pewny token kropek, razem ≥6 znaków) -> znacznik miejsca do wpisania."""
    toks = [t for t in text.split(" ") if t]
    out: list[str] = []
    i = 0
    while i < len(toks):
        j = i
        while j < len(toks) and (_is_leader(toks[j]) or _is_weak_leader(toks[j])):
            j += 1
        run = toks[i:j]
        strong = sum(1 for t in run if _is_leader(t))
        if run and strong and sum(len(t) for t in run) >= 6 and strong >= len(run) / 2:
            out.append(LINE_MARK)
            i = j
        else:
            out.append(toks[i])
            i += 1
    return " ".join(out)


def to_lines(doc: SourceDoc) -> list[Line]:
    src = doc.blocks
    if doc.ocr:
        src = [b.model_copy(update={"text": denoise_ocr(b.text)}) if b.kind == "text" else b for b in src]
    blocks: list[SourceBlock] = []
    split_ids: set[int] = set()
    for b in src:
        parts = _split_columns(b)
        if len(parts) > 1:
            split_ids.update(id(x) for x in parts)
        blocks.extend(parts)
    if blocks and all(b.bbox for b in blocks):
        blocks.sort(key=lambda b: (b.page, round((b.bbox.y + b.bbox.h / 2) / 4), b.bbox.x))  # type: ignore[union-attr]
    lines: list[Line] = []
    groups: list[list[SourceBlock]] = []
    for b in blocks:
        if groups and _merge(groups[-1][-1], b) and not (id(b) in split_ids and groups[-1][-1].id == b.id):
            groups[-1].append(b)
        else:
            groups.append([b])
    for g in groups:
        b0 = g[0]
        bbs = [b.bbox for b in g if b.bbox]
        bbox = None
        if bbs:
            x, y = min(b.x for b in bbs), min(b.y for b in bbs)
            bbox = BBox(x=x, y=y, w=max(b.x + b.w for b in bbs) - x, h=max(b.y + b.h for b in bbs) - y)
        if len(g) > 1:
            text = " ".join(
                LINE_MARK if b.kind == "line" else b.text.strip() for b in g if b.kind == "line" or b.text.strip()
            )
        else:
            text = b0.text.strip()
        text = re.sub(r"(\d)\s+\)", r"\1)", text)
        if text.startswith("(") and text.count(")") > text.count("("):
            text = re.sub(r"\)\)+$", ")", text)  # literówka '(nr telefonu))'
        st = b0.style
        lines.append(
            Line(
                page=b0.page,
                text=text,
                block_ids=[b.id for b in g],
                bbox=bbox,
                font=st.font_size if st else None,
                bold=bool(st and st.bold),
                heading=st.heading if st else None,
                centered=bool(st and st.centered),
                conf=min(b.confidence for b in g),
                kind="line" if all(b.kind == "line" for b in g) else b0.kind if b0.kind != "line" else "text",
                checked=b0.checked,
                table=b0.table,
                row=b0.row,
                col=b0.col,
                tags={"input"} if any(b.kind == "line" for b in g) else set(),
            )
        )
    return lines


def median_font(lines: list[Line]) -> float:
    fs = [ln.font for ln in lines if ln.font]
    return statistics.median(fs) if fs else 10.0
