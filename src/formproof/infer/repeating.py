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
    # opis i zgody w sygnaturze: dwie różne sekcje zgód (oświadczenia, RODO) to nie powtórzony blok
    kids = tuple(
        (
            c.type,
            fold(c.title),
            fold(c.description or "")[:120],
            tuple(
                fold(x.description)[:80]
                for x in (c.consent_section_config.consents if c.consent_section_config else [])
            ),
        )
        for c in f.children
    )
    when = tuple((w.when_key, w.equals, w.negate) for w in f.show_when)
    return (fold(_TRAIL_NO.sub("", f.title)), kids, when)


def _consent_key(f: DraftField) -> tuple[str, ...] | None:
    """Sekcja z jedną CONSENT_SECTION -> treści zgód (klucz scalania kolejnych fragmentów tej samej klauzuli)."""
    if f.type != "SECTION" or len(f.children) != 1 or f.children[0].type != "CONSENT_SECTION":
        return None
    cfg = f.children[0].consent_section_config
    return tuple(fold(c.description) for c in cfg.consents) if cfg else None


def _merge_consents(fields: list[DraftField]) -> list[DraftField]:
    """Klauzula RODO pocięta nagłówkami na kilka sekcji zgód z tą samą zgodą -> jedna sekcja."""
    out: list[DraftField] = []
    for f in fields:
        k = _consent_key(f)
        prev = out[-1] if out else None
        if k and prev is not None and _consent_key(prev) == k:
            a, b = prev.children[0], f.children[0]
            desc = " ".join(x for x in (a.description, b.description) if x)
            a.description = desc[:1200] + ("…" if len(desc) > 1200 else "")
            a.evidence = [*a.evidence, *b.evidence]
            continue
        out.append(f)
    return out


def merge_repeating(draft: DraftForm) -> DraftForm:
    for tab in draft.tabs:
        tab.fields = _merge_consents(tab.fields)
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
