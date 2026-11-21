"""Normalizacja bloków SourceDoc do linii (kolejność czytania) + pomocnicze dopasowania tekstu."""

from __future__ import annotations

import re
import statistics
import unicodedata
from dataclasses import dataclass, field

from ..types.source import BBox, SourceBlock, SourceDoc

PLACEHOLDER = re.compile(r"[.…_]{3,}|…+|_{2,}")
PAREN_HINT = re.compile(r"^\(([^()]{2,120})\)$")
FOOTNOTE_MARK = re.compile(r"^\d{1,2}\s?\)$")


def fold(s: str) -> str:
    """Małe litery bez polskich znaków (do dopasowań regex)."""
    s = s.replace("ł", "l").replace("Ł", "L")
    return "".join(c for c in unicodedata.normalize("NFKD", s.lower()) if not unicodedata.combining(c))


def clean(s: str) -> str:
    s = PLACEHOLDER.sub(" ", s).replace("`", " ")
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


def to_lines(doc: SourceDoc) -> list[Line]:
    blocks = list(doc.blocks)
    if blocks and all(b.bbox for b in blocks):
        blocks.sort(key=lambda b: (b.page, round((b.bbox.y + b.bbox.h / 2) / 4), b.bbox.x))  # type: ignore[union-attr]
    lines: list[Line] = []
    groups: list[list[SourceBlock]] = []
    for b in blocks:
        if groups and _merge(groups[-1][-1], b):
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
        text = " ".join(b.text.strip() for b in g if b.text.strip())
        text = re.sub(r"(\d)\s+\)", r"\1)", text)
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
