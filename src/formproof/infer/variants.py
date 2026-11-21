"""Kilka formularzy w jednym pliku: 'Rodzaje wniosków: I. … II. … III. …', a dalej pełne podformularze.

Dzielimy dokument na warianty po nagłówkach z numerem rzymskim (I., II., …), inferujemy każdy osobno
i scalamy w jeden formularz: na początku wybór „Rodzaj wniosku”, sekcje wariantu pokazywane warunkowo (SHOW),
sekcje identyczne we wszystkich wariantach – raz, bez warunku.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from difflib import SequenceMatcher

from ..types.draft import DraftField, DraftForm, DraftOption, DraftTab, Evidence, ShowWhen, iter_draft
from ..types.source import SourceDoc
from .lines import Line, clean, fold

# OCR myli I z l oraz | – normalizujemy przed odczytem liczby
ROMAN_HEAD = re.compile(r"^\s*([IVXl|]{1,5})\s*\.\s+(\S.{4,})$")
ARABIC_ONE = re.compile(r"^\s*1\s*[.)]\s+\S")
_ROMAN = {"I": 1, "V": 5, "X": 10}
MIN_PART_LINES = 12
CHOICE_TITLE = "Wybierz rodzaj wniosku"


def _roman(s: str) -> int | None:
    s = s.replace("l", "I").replace("|", "I")
    if not re.fullmatch(r"X{0,3}(IX|IV|V?I{0,3})", s) or not s:
        return None
    total = 0
    for i, ch in enumerate(s):
        v = _ROMAN[ch]
        total += -v if i + 1 < len(s) and _ROMAN[s[i + 1]] > v else v
    return total


def _words(s: str) -> list[str]:
    return clean(s).split()


def _same(words: list[str]) -> bool:
    """To samo słowo mimo literówki OCR ('Whiosek' = 'Wniosek')."""
    a = fold(words[0])
    return all(SequenceMatcher(None, a, fold(w)).ratio() >= 0.8 for w in words[1:])


def _common_title(titles: list[str]) -> str:
    """'Wniosek o przyznanie A / B / C Rady Miasta' -> 'Wniosek o przyznanie A, B lub C Rady Miasta'."""
    ws = [_words(t) for t in titles]
    pre = 0
    while all(len(w) > pre for w in ws) and _same([w[pre] for w in ws]):
        pre += 1
    suf = 0
    while all(len(w) > pre + suf for w in ws) and _same([w[-1 - suf] for w in ws]):
        suf += 1
    mids = [" ".join(w[pre : len(w) - suf]) for w in ws]
    if pre == 0 or any(not m for m in mids):
        return " / ".join(clean(t) for t in titles)
    head, tail = ws[0][:pre], ws[0][len(ws[0]) - suf :] if suf else []
    mid = ", ".join(mids[:-1]) + " lub " + mids[-1]
    return " ".join([*head, mid, *tail])


def _by_roman(lines: list[Line]) -> list[tuple[int, list[str]]] | None:
    """I..n (n≥2): każdy numer w spisie i jako nagłówek albo z tym samym początkiem tytułu; numeracja od nowa."""
    occ: dict[int, list[int]] = {}
    for i, ln in enumerate(lines):
        m = ROMAN_HEAD.match(ln.text)
        if m and (n := _roman(m.group(1))) is not None:
            occ.setdefault(n, []).append(i)
    k = 0
    while k + 1 in occ:
        k += 1
    if k < 2:
        return None

    def body(i: int) -> str:
        m = ROMAN_HEAD.match(lines[i].text)
        return clean(m.group(2)) if m else ""

    starts = [occ[n][-1] for n in range(1, k + 1)]
    listed = all(len(occ[n]) >= 2 for n in range(1, k + 1))
    same_start = len({" ".join(fold(body(s)).split()[:2]) for s in starts}) == 1
    if not (listed or same_start) or not _restarts(lines, starts):
        return None
    return [(s, [body(i) for i in occ[n]]) for n, s in zip(range(1, k + 1), starts, strict=True)]


def _by_list(lines: list[Line]) -> list[tuple[int, list[str]]] | None:
    """Spis bez numerów (DOCX gubi numerację list): ≥2 kolejne linie-tytuły, które wracają dalej w tej samej
    kolejności jako nagłówki (także złamane na dwie linie)."""
    keys = [fold(clean(ln.text)) for ln in lines]
    for i in range(min(len(lines), 40)):
        run: list[int] = []
        j = i
        while j < len(lines) and len(keys[j]) >= 15 and keys[j] not in {keys[r] for r in run}:
            run.append(j)
            j += 1
        if len(run) < 2:
            continue
        starts: list[int] = []
        pos = run[-1] + 1
        for r in run:
            hit = next(
                (
                    q
                    for q in range(pos, len(lines))
                    if keys[q] == keys[r] or (len(keys[q]) >= 0.6 * len(keys[r]) and keys[r].startswith(keys[q]))
                ),
                None,
            )
            if hit is None:
                break
            starts.append(hit)
            pos = hit + 1
        if len(starts) == len(run) >= 2:
            return [(s, [clean(lines[r].text), clean(lines[s].text)]) for r, s in zip(run, starts, strict=True)]
    return None


def _restarts(lines: list[Line], starts: list[int]) -> bool:
    ends = [*starts[1:], len(lines)]
    return all(any(ARABIC_ONE.match(ln.text) for ln in lines[s + 1 : e]) for s, e in zip(starts, ends, strict=True))


def split_variants(doc: SourceDoc, lines: list[Line]) -> list[tuple[str, SourceDoc]] | None:
    """Warianty wniosku w jednym pliku albo None (zwykły formularz)."""
    found = _by_roman(lines) or _by_list(lines)
    if not found:
        return None
    starts = [s for s, _ in found]
    ends = [*starts[1:], len(lines)]
    if any(b <= a for a, b in zip(starts, starts[1:], strict=False)) or any(
        e - s < MIN_PART_LINES for s, e in zip(starts, ends, strict=True)
    ):
        return None
    out: list[tuple[str, SourceDoc]] = []
    for (s, names), e in zip(found, ends, strict=True):
        head = names[-1]
        full = max(names, key=len)
        drop: set[str] = set()
        # pełny tytuł ze spisu, jeśli nagłówek złamał się na dwie linie ('… Rady Miasta' + 'Zgierza')
        if s + 1 < e and fold(f"{head} {clean(lines[s + 1].text)}") == fold(full):
            drop.update(lines[s + 1].block_ids)
        title = (full if fold(full).startswith(fold(head)) else head).strip("_ ")
        ids = {b for ln in lines[s:e] for b in ln.block_ids} - drop
        out.append((title, doc.model_copy(update={"blocks": [b for b in doc.blocks if b.id in ids]})))
    return out


def _sig(f: DraftField) -> tuple[object, ...]:
    consent = f.consent_section_config.model_dump_json() if f.consent_section_config else ""
    return (
        f.type,
        fold(f.title),
        fold(f.description or ""),
        consent,
        tuple(o.name for o in f.options),
        tuple(_sig(c) for c in f.children),
    )


def _self_contained(f: DraftField) -> bool:
    keys = {x.key for x in iter_draft([f])}
    return all(w.when_key in keys for x in iter_draft([f]) for w in x.show_when)


def merge_variants(parts: list[tuple[str, DraftForm]], key: Callable[[], str]) -> DraftForm:
    titles = [t for t, _ in parts]
    choice = DraftField(
        key=key(),
        type="RADIO",
        title=CHOICE_TITLE,
        options=[DraftOption(name=t) for t in titles],
        validation=["REQUIRED"],
        confidence=0.85,
        evidence=[Evidence(by="rules", reason=f"dokument zawiera {len(titles)} rodzaje wniosków (I–{len(titles)})")],
    )
    head = DraftField(
        key=key(),
        type="SECTION",
        title="Rodzaj wniosku",
        children=[choice],
        confidence=0.85,
        evidence=choice.evidence,
    )

    tab_order: list[str] = []
    meta: dict[str, DraftTab] = {}
    finish: DraftTab | None = None
    for _, d in parts:
        for t in d.tabs:
            if t.type == "FINISH":
                finish = finish or t
                continue
            if t.title not in meta:
                tab_order.append(t.title)
                meta[t.title] = t

    tabs: list[DraftTab] = []
    for ti, tt in enumerate(tab_order):
        per = [next((t.fields for t in d.tabs if t.title == tt and t.type != "FINISH"), []) for _, d in parts]
        fields: list[DraftField] = [head] if ti == 0 else []
        shared: set[int] = set()
        for f in per[0]:
            if not _self_contained(f):
                continue
            twins = [next((g for g in other if _sig(g) == _sig(f)), None) for other in per[1:]]
            if all(twins):
                shared.add(id(f))
                for g in twins:
                    if g is not None:
                        shared.add(id(g))
        emitted: set[tuple[object, ...]] = set()
        for (vt, _), fs in zip(parts, per, strict=True):
            for f in fs:
                if id(f) in shared:
                    if _sig(f) not in emitted:
                        emitted.add(_sig(f))
                        fields.append(f)
                    continue
                f.show_when = [*f.show_when, ShowWhen(when_key=choice.key, equals=vt)]
                fields.append(f)
        tabs.append(DraftTab(title=tt, fields=fields, confidence=meta[tt].confidence, evidence=meta[tt].evidence))
    if finish:
        tabs.append(finish)
    tconf = min(d.title_confidence for _, d in parts)
    return DraftForm(
        title=_common_title(titles),
        title_confidence=round(min(0.9, tconf), 2),
        title_evidence=[Evidence(by="rules", reason="tytuł złożony z tytułów wariantów wniosku")],
        tabs=tabs,
    )
