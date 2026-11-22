"""Formularze z numerowanymi pozycjami (deklaracje urzędowe: 'A. ORGAN…', 'B.1 DANE…', '8. Kraj | 9. Województwo').

Każda pozycja 'N. Etykieta' to jedno pole; numery rosną w całym dokumencie, więc numerowane opcje kratek
('1. właściciel') i punkty pouczeń ('1. W przypadku…') nie są brane za pozycje. Nagłówki sekcji to litera
(z numerem podsekcji) i tekst wersalikami. Kratki pod pozycją = opcje wyboru tej pozycji.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from . import concepts as C
from .lines import Line, clean, fold

POS = re.compile(r"(?:(?<=\s)|^)(\d{1,3})\.\s+(?=[^\W\d_])")
BARE = re.compile(r"^(\d{1,3})\.$")  # sam numer pozycji w komórce, treść w kratce obok ('72.' + '☐ Wyrażam zgodę…')
NUM_OPT = re.compile(r"^(\d{1,3})\.\s+")
HEAD = re.compile(r"^([A-Z](?:\.\d+)*)\.?\s+(\S.*)$")
DATE_MASK = re.compile(r"^[-–\s]*(?:[DMR]\s*){2,}[-–\sDMR]*$")
MONEY = re.compile(r"\bzł\b|\bliczba\b|\bstawka\b|\bkwota\b|\bsuma\b|\bwysokość\b", re.I)
MIN_POSITIONS = 12
MAX_STEP = 6


def _upper_ratio(s: str) -> float:
    letters = [c for c in s if c.isalpha()]
    return sum(c.isupper() for c in letters) / len(letters) if letters else 0.0


def _chunks(t: str) -> list[tuple[int, int, int]]:
    """(numer, początek, koniec etykiety) dla każdego 'N. ' w linii."""
    ms = list(POS.finditer(t))
    return [(int(m.group(1)), m.end(), ms[k + 1].start() if k + 1 < len(ms) else len(t)) for k, m in enumerate(ms)]


def is_positional(lines: list[Line]) -> bool:
    """Najdłuższy rosnący ciąg pozycji (krok ≤ MAX_STEP, start ≤ 3) ma co najmniej MIN_POSITIONS elementów."""
    last, n = 0, 0
    for ln in lines:
        if ln.kind == "checkbox" or ln.consumed:
            continue
        for num, _, _ in _chunks(clean(ln.text)):
            if (last == 0 and num <= 3) or (last < num <= last + MAX_STEP):
                last, n = num, n + 1
    return n >= MIN_POSITIONS


@dataclass
class _Pos:
    num: int
    label: str
    lines: list[Line]
    opts: list[tuple[str, Line]] = field(default_factory=list)


def _title(label: str) -> tuple[str, str | None]:
    """Etykieta pozycji -> (tytuł, opis z nawiasu)."""
    t = clean(label).strip(" :")
    desc = None
    m = re.search(r"\s*\(([^()]{3,})\)\s*$", t)
    if m:
        desc = m.group(1).strip()
        t = t[: m.start()].strip()
    # wartość wpisana wersalikami za etykietą ('Miejscowość GDYNIA') – nie część tytułu
    t = re.sub(r"(?<=[a-ząćęłńóśźż])\s+[A-ZĄĆĘŁŃÓŚŹŻ]{3,}(?:\s+[A-ZĄĆĘŁŃÓŚŹŻ]{3,})*$", "", t)
    return (t[:1].upper() + t[1:]) if t else t, desc


def positional_sections(
    lines: list[Line],
    sections: list[Any],
    new_section: Callable[[str, int, Line], Any],
    item_cls: type,
    choice_cls: type,
) -> bool:
    """Wypełnia `sections` (lista Section z _infer_one). False = dokument nie jest formularzem pozycyjnym."""
    if not is_positional(lines):
        return False
    cur = sections[-1]
    last = 0
    open_: _Pos | None = None
    head_open = False
    head_id = ""

    def close() -> None:
        nonlocal open_
        p, open_ = open_, None
        if p is None:
            return
        title, desc = _title(p.label)
        subs = [(n, p.label[a:b].strip(" :")) for n, a, b in _chunks(p.label)]
        yn = [o for o in p.opts if fold(o[0]) in ("tak", "nie")]
        if len(subs) >= 2 and subs[0][0] == 1 and yn and len(yn) == len(p.opts):
            # 'Rodzaje załączników 1. Załącznik A 2. Załącznik B …' + pary TAK/NIE w wierszach
            for k, (_, sub) in enumerate(subs):
                sub_t, _ = _title(sub)
                if not sub_t:
                    continue
                if 2 * k + 1 < len(yn):
                    ch = choice_cls(title=sub_t, lines=list(p.lines) + [yn[2 * k][1], yn[2 * k + 1][1]])
                    ch.options.extend([("Tak", yn[2 * k][1]), ("Nie", yn[2 * k + 1][1])])
                    cur.entries.append(ch)
                else:
                    sp = C.Spec(sub_t, reason=f"pozycja {p.num}: podpunkt bez kratek TAK/NIE")
                    cur.entries.append(item_cls(spec=sp, lines=list(p.lines), optional=True))
            return
        if not title and not p.opts:
            return
        if p.opts:
            if len(p.opts) == 1:
                # pojedyncza kratka oświadczenia: zdanie = tekst kratki + reszta etykiety
                opt = p.opts[0][0]
                frag = clean(p.label)[:1].islower()  # etykieta pozycji to dokończenie zdania z kratki
                text = clean(f"{opt} {clean(p.label)}") if frag else (opt if len(opt) > len(title) else title)
                ch = choice_cls(title=text, lines=list(p.lines), multi=True)
                ch.options.append(("Tak", p.opts[0][1]))
                cur.entries.append(ch)
                return
            # tytuł pytania kończy się na podpowiedzi '(zaznaczyć …)' albo dwukropku; dalej sklejony tekst opcji
            q = re.sub(r"\s*\([^()]*zaznacz[^()]*\).*$", "", title)
            q = q.split(":")[0].strip() or title
            ch = choice_cls(title=q, lines=list(p.lines), multi=bool(C.MULTI_HINT.search(fold(p.label))))
            for name, ln in p.opts:
                ch.options.append((name, ln))
                ch.lines.append(ln)
            cur.entries.append(ch)
            for name, ln in p.opts:
                if re.search(r"\bdata\b", fold(name)):
                    short = re.split(r"\s+[-–]\s+data\b", name)[0].strip()
                    sp = C.Spec(f"Data – {short}", "DATEPICKER", reason="data przy opcji wyboru (maska DD-MM-RRRR)")
                    it = item_cls(spec=sp, lines=[ln])
                    cur.entries.append(it)
                    cur.conds[id(it)] = (ch, name)
            return
        specs = C.specs_for_label(title)
        if not specs:
            return
        name_pair = bool(C.NAME_PAIR.search(fold(title)))
        addr_set = all(sp.group == "address" for sp in specs)  # 'Adres zamieszkania' -> standard adresu
        if len(specs) > 1 and not name_pair and not addr_set and not all(sp.validation for sp in specs):
            # jedna pozycja = jedno pole ('Numer nieruchomości/domu'); dzielimy tylko pary typowane (NIP/REGON)
            typed = [sp for sp in specs if sp.type != "TEXT_FIELD" or sp.validation]
            specs = [typed[0] if typed else C.Spec(title, reason="etykieta pozycji")]
            specs[0].title = title
        if re.search(r"\bopis\b", fold(title)) or (len(specs) > 3 and len(title.split()) > 3):
            specs = [C.Spec(title, "TEXTAREA", reason="opis miejsca – pole opisowe")]  # 'Adres lub opis miejsca …'
        if MONEY.search(title):
            # 'Wysokość opłaty zł' -> bez jednostki; stała stawka ('… 38 zł') zostaje w tytule
            t2 = title if re.search(r"\bstawk", fold(title)) else re.sub(r"\s+zł\s*$", "", title)
            specs = [C.Spec(t2, "NUMBER", reason=f"pozycja {p.num}: kwota/liczba")]
        elif len(specs) == 1 and specs[0].type == "TEXT_FIELD" and not specs[0].validation and not specs[0].group:
            specs[0].title = title
        for sp in specs:
            sp.reason = f"pozycja {p.num} formularza; " + sp.reason
            if desc and sp.type == "TEXT_FIELD" and len(desc) > 60:
                sp.type = "TEXTAREA"
            cur.entries.append(item_cls(spec=sp, lines=list(p.lines)))

    for ln in lines:
        if ln.consumed:
            continue
        t = clean(ln.text)
        if not t:
            continue
        if ln.kind == "checkbox":
            txt = re.sub(r"^\d{1,2}\.\s*", "", t).strip()
            if len(txt) <= 1 or DATE_MASK.match(txt):
                continue  # 'X', '=' (znaki działań w tabeli) i maski daty
            mn = NUM_OPT.match(t)
            if mn and int(mn.group(1)) >= 10 and last < int(mn.group(1)) <= last + MAX_STEP:
                close()  # '72. Wyrażam zgodę …' – kratka będąca samodzielną pozycją
                last = int(mn.group(1))
                open_ = _Pos(last, "", [ln], [(txt, ln)])
                continue
            if open_ is None:
                cur.texts.append(ln)
                continue
            if txt[:1].islower() and open_.opts and not mn and NUM_OPT.match(open_.opts[-1][1].text.strip()):
                n0, l0 = open_.opts[-1]
                open_.opts[-1] = (clean(n0 + " " + txt.rstrip(":")), l0)
                continue
            open_.opts.append((txt.rstrip(":"), ln))
            continue
        m = HEAD.match(t)
        if m and _upper_ratio(m.group(2).split("(")[0]) > 0.6 and not POS.match(t):
            if m.group(1) == head_id:
                cur.lines.append(ln)  # ta sama komórka nagłówka wyekstrahowana drugi raz
                continue
            close()
            head_id = m.group(1)
            cur = new_section(f"{m.group(1)}. {m.group(2)}", m.group(1).count(".") + 1, ln)
            hf = fold(m.group(2))
            if cur.kind == "consent" and not re.search(r"klauzul|rodo|przetwarzani", hf):
                cur.kind = ""  # 'OŚWIADCZENIE O WYSOKOŚCI OPŁATY' to część deklaracji, nie zgoda
            if cur.kind == "person":
                # osoba składająca = pierwsza sekcja danych (z podsekcjami); kolejne (współmałżonek, dane
                # nieruchomości) i 'opłata dla właścicieli' to zwykłe sekcje
                earlier = [x for x in sections if x.kind == "person"]
                if not re.search(r"\bdane\b|\bpodmiot", hf) or (
                    earlier and not any(x.level < cur.level for x in earlier[-1:])
                ):
                    cur.kind = ""
            sections.append(cur)
            head_open = True
            continue
        bm = BARE.match(t)
        if bm and last < int(bm.group(1)) <= last + MAX_STEP:
            close()
            last = int(bm.group(1))
            open_ = _Pos(last, "", [ln])
            continue
        if head_open and _upper_ratio(t) > 0.8 and not POS.match(t) and len(t) < 120:
            cur.lines.append(ln)  # dalszy ciąg nagłówka wersalikami
            continue
        head_open = False
        f = fold(t)
        if (
            len(t) < 90
            and not POS.match(t)
            and t[:1].isupper()
            and (ln.kind != "cell" or _upper_ratio(t) > 0.6)  # komórki tabeli to treść deklaracji, nie nagłówki
            and (C.SECTION_SKIP.search(f) or C.SECTION_CONSENT.search(f))
        ):
            close()
            cur = new_section(t.rstrip(":"), 1, ln)
            sections.append(cur)
            continue
        if cur.kind in ("skip", "consent"):
            if cur.kind == "consent":
                cur.texts.append(ln)
            continue
        accepted = [(n, a, b) for n, a, b in _chunks(t) if last < n <= last + MAX_STEP]
        # tylko rosnące w obrębie linii
        acc: list[tuple[int, int, int]] = []
        for n, a, b in accepted:
            if not acc or n > acc[-1][0]:
                acc.append((n, a, b))
        if acc:
            pre = t[: acc[0][1]].rsplit(str(acc[0][0]) + ".", 1)[0].strip()
            if pre and open_ is not None and not open_.opts:
                open_.label += " " + pre
            for k, (n, a, _) in enumerate(acc):
                close()
                end = acc[k + 1][1] if k + 1 < len(acc) else len(t)
                label = t[a:end]
                if k + 1 < len(acc):
                    label = label.rsplit(str(acc[k + 1][0]) + ".", 1)[0]
                open_ = _Pos(n, label.strip(), [ln])
                last = n
            continue
        if open_ is not None and not open_.opts and t[:1].islower() and len(open_.label) < 200:
            open_.label += " " + t
            open_.lines.append(ln)
            continue
        cur.texts.append(ln)
    close()
    return True
