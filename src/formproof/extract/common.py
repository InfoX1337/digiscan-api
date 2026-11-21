"""Wspólne narzędzia ekstrakcji: budowniczy bloków i segmentacja tekstu (checkboxy, linie do wpisania)."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any

from ..types.source import BBox, BlockKind, BlockStyle, SourceBlock

CHECKED_GLYPHS = "☑☒■✔✓🗹"
UNCHECKED_GLYPHS = "☐□▢❏❑"
CHECK_GLYPHS = CHECKED_GLYPHS + UNCHECKED_GLYPHS

_TOKEN_RE = re.compile(
    r"(?P<cb>[" + re.escape(CHECK_GLYPHS) + r"]|\[\s?[xXvV]?\s?\])"
    r"|(?P<line>(?:[._…·]\s?){4,}|-{6,})"
)


def expired(deadline: float | None) -> bool:
    return deadline is not None and time.monotonic() > deadline


@dataclass
class Seg:
    kind: BlockKind  # text | checkbox | line
    text: str
    start: int  # zakres znaków w tekście wejściowym
    end: int
    checked: bool | None = None


def segment(text: str) -> list[Seg]:
    """Dzieli linię tekstu na segmenty: tekst, checkbox (etykieta = tekst po prawej), linia do wpisania."""
    raw: list[Seg] = []
    pos = 0
    for m in _TOKEN_RE.finditer(text):
        if m.start() > pos:
            raw.append(Seg("text", text[pos : m.start()], pos, m.start()))
        if m.group("cb") is not None:
            g = m.group("cb")
            checked = g in CHECKED_GLYPHS or (len(g) > 1 and g[1:-1].strip().lower() in ("x", "v"))
            raw.append(Seg("checkbox", "", m.start(), m.end(), checked))
        else:
            raw.append(Seg("line", "", m.start(), m.end()))
        pos = m.end()
    if pos < len(text):
        raw.append(Seg("text", text[pos:], pos, len(text)))
    out: list[Seg] = []
    i = 0
    while i < len(raw):
        s = raw[i]
        if s.kind == "text":
            if s.text.strip():
                out.append(Seg("text", s.text.strip(), s.start, s.end))
        elif s.kind == "checkbox":
            end = s.end
            label = ""
            if i + 1 < len(raw) and raw[i + 1].kind == "text":
                label = raw[i + 1].text.strip()
                end = raw[i + 1].end
                i += 1
            out.append(Seg("checkbox", label, s.start, end, s.checked))
        else:
            out.append(s)
        i += 1
    return out


class Builder:
    """Zbiera bloki i nadaje stabilne id `p{page}-b{n}`."""

    def __init__(self) -> None:
        self.blocks: list[SourceBlock] = []
        self._n: dict[int, int] = {}

    def add(
        self,
        page: int,
        kind: BlockKind,
        text: str,
        bbox: BBox | None = None,
        style: BlockStyle | None = None,
        **kw: Any,
    ) -> SourceBlock:
        n = self._n.get(page, 0) + 1
        self._n[page] = n
        b = SourceBlock(id=f"p{page}-b{n}", page=page, kind=kind, text=text, bbox=bbox, style=style, **kw)
        self.blocks.append(b)
        return b

    def add_text(
        self,
        page: int,
        text: str,
        style: BlockStyle | None = None,
        **kw: Any,
    ) -> list[SourceBlock]:
        """Tekst bez układu: rozbija na text/checkbox/line."""
        out: list[SourceBlock] = []
        for s in segment(text):
            if s.kind == "text":
                out.append(self.add(page, "text", s.text, style=style, **kw))
            elif s.kind == "checkbox":
                out.append(self.add(page, "checkbox", s.text, style=style, checked=bool(s.checked), **kw))
            else:
                out.append(self.add(page, "line", "", **kw))
        return out
