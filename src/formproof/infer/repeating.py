"""Powtórzone bloki ('Dane osobowe podopiecznego' ×4) -> jedna REPEATING_SECTION.

Scalamy tylko sąsiednie sekcje o tym samym tytule, identycznym układzie pól i tych samych warunkach SHOW.
Heurystyka działa na strukturze, nie na konkretnych tytułach.
"""

from __future__ import annotations

import re

from ..types.draft import DraftField, DraftForm, Evidence
from .lines import fold

_TRAIL_NO = re.compile(r"[\s.:()\-–]*\b(?:nr\s*)?\d{1,2}\s*[.)]?\s*$")


def _sig(f: DraftField) -> tuple[object, ...]:
    kids = tuple((c.type, fold(c.title)) for c in f.children)
    when = tuple((w.when_key, w.equals, w.negate) for w in f.show_when)
    return (fold(_TRAIL_NO.sub("", f.title)), kids, when)


def merge_repeating(draft: DraftForm) -> DraftForm:
    for tab in draft.tabs:
        out: list[DraftField] = []
        i = 0
        fields = tab.fields
        while i < len(fields):
            f = fields[i]
            j = i + 1
            if f.type == "SECTION" and f.children:
                while j < len(fields) and fields[j].type == "SECTION" and _sig(fields[j]) == _sig(f):
                    j += 1
            if j - i >= 2:
                f = f.model_copy(
                    update={
                        "type": "REPEATING_SECTION",
                        "title": _TRAIL_NO.sub("", f.title) or f.title,
                        "evidence": [
                            *f.evidence,
                            Evidence(
                                by="rules",
                                reason=f"{j - i} powtórzone bloki o tym samym układzie -> sekcja powtarzająca się",
                            ),
                        ],
                    }
                )
            out.append(f)
            i = j
        tab.fields = out
    return draft
