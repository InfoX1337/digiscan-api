"""DICT (runda 2): słowniki predefiniowane, dane inicjalne (MLPZ), propozycje nowych słowników.

Funkcje czyste: wejściowy DraftForm nie jest modyfikowany (praca na kopii).
"""

from __future__ import annotations

import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

from ..types.draft import DraftField, DraftForm, DraftOption, Evidence, iter_draft
from ..types.stages import DictResult, ProposedDict

_DATA = Path(__file__).parent / "data"
_DROPDOWN_OK = ("TEXT_FIELD", "SELECT", "RADIO", "CHECKBOX")


def _fold(s: str) -> str:
    s = s.lower().replace("ł", "l")
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9+ ]+", " ", s).strip()


def _words(s: str) -> str:
    return re.sub(r"\s+", " ", _fold(s))


@lru_cache(maxsize=1)
def _load() -> dict[str, dict[str, object]]:
    out: dict[str, dict[str, object]] = {}
    for p in sorted(_DATA.glob("*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        out[str(d["name"])] = d
    return out


def list_dictionaries() -> list[dict[str, object]]:
    return [
        {
            "name": n,
            "count": len(d["items"]),  # type: ignore[arg-type]
            "sample": bool(d.get("sample", False)),
            "description": d.get("description", ""),
        }
        for n, d in _load().items()
    ]


def get_dictionary(name: str) -> list[str] | None:
    d = _load().get(name)
    if d is None:
        return None
    items: list[str] = list(d["items"])  # type: ignore[call-overload]
    return items


# --- dopasowanie pola do słownika -------------------------------------------------------------

# (nazwa słownika, wzorzec etykiety po złożeniu znaków, wymaga_listy) – "wymaga_listy": pole musi być już
# listą/mieć opcje (słowniki TERYT-owe tylko próbkowe: nie zastępujemy nimi pól tekstowych).
_LABEL_RULES: list[tuple[str, re.Pattern[str], bool]] = [
    (
        "Numery kierunkowe",
        re.compile(r"\b(numer(y)? kierunkow\w*|kod kraju|prefiks\w*( telefon\w*)?|kierunkowy)\b"),
        False,
    ),
    ("Kraje", re.compile(r"\b(kraj|panstwo|obywatelstwo|narodowosc)\b"), False),
    ("Województwo", re.compile(r"\bwojewodztw\w*\b"), False),
    ("Powiat", re.compile(r"\bpowiat\w*\b"), True),
    ("Gmina", re.compile(r"\bgmin\w*\b"), True),
    ("Miejscowość", re.compile(r"\bmiejscowosc\w*\b"), True),
]
_LABEL_EXCLUDE = re.compile(r"\b(kod|ulica|numer|nr|organ|urzad|wojewoda|starosta|wojt)\b")
_LABEL_EXCLUDE_NUM = re.compile(r"\b(numer|nr)\b(?!.*(kierunkow|kraju))")
_OVERLAP_DICTS = ("Kraje", "Województwo", "Numery kierunkowe")


@lru_cache(maxsize=1)
def _item_sets() -> dict[str, set[str]]:
    sets: dict[str, set[str]] = {}
    for n in _OVERLAP_DICTS:
        items = get_dictionary(n) or []
        keys = {_words(i) for i in items}
        if n == "Numery kierunkowe":
            keys |= {_words(i.split(" ")[0]) for i in items}
        sets[n] = keys
    return sets


def _norm_option(name: str, dict_name: str) -> str:
    w = _words(name)
    if dict_name == "Województwo":
        w = re.sub(r"^(wojewodztwo|woj)\s+", "", w)
        w = re.sub(r"\s+(wojewodztwo)$", "", w)
    return w


def _by_options(opts: list[DraftOption]) -> str | None:
    if len(opts) < 3:
        return None
    for n, keys in _item_sets().items():
        hit = sum(1 for o in opts if _norm_option(o.name, n) in keys)
        if hit / len(opts) >= 0.7 and hit >= 3:
            return n
    return None


def _by_label(f: DraftField) -> str | None:
    t = _words(f.title)
    has_list = f.type != "TEXT_FIELD" or bool(f.options)
    for name, pat, need_list in _LABEL_RULES:
        if not pat.search(t):
            continue
        if name != "Numery kierunkowe" and _LABEL_EXCLUDE.search(t):
            continue
        if name == "Numery kierunkowe" and f.type == "TEXT_FIELD" and not f.options and "kierunkow" not in t:
            continue
        if need_list and not has_list:
            continue
        return name
    return None


def _assign(f: DraftField, name: str, reason: str) -> None:
    f.type = "SELECT"
    f.options = []
    f.dictionary_name = name
    if not any(e.by == "dict" for e in f.evidence):
        f.evidence = [*f.evidence, Evidence(block_ids=[], by="dict", reason=reason)]


def _match_dictionary(f: DraftField) -> None:
    if f.type not in _DROPDOWN_OK:
        return
    if f.dictionary_name:
        # idempotencja: słownik już ustawiony (np. przez INFER) – tylko dopilnuj typu/opcji wg reguł
        if f.dictionary_name in _load():
            _assign(f, f.dictionary_name, f"pole korzysta ze słownika „{f.dictionary_name}”")
        return
    name = _by_label(f)
    why = "etykieta wskazuje na słownik"
    if name is None and f.type != "TEXT_FIELD":
        name = _by_options(f.options)
        why = "opcje pola pokrywają się ze słownikiem"
    if name is None:
        return
    _assign(f, name, f"{why} „{name}” (lista rozwijana zamiast wpisywania ręcznego)")


# --- dane inicjalne (MLPZ) ---------------------------------------------------------------------

_APPLICANT_INCLUDE = re.compile(
    r"\b(twoje dane|twoj\w*|wnioskodaw\w*|wnioskujac\w*|skladajac\w*|dane osobow\w*|adres zamieszkania|"
    r"dane do kontaktu|dane kontaktow\w*|kontakt|adres korespondencyjny)\b"
)
_APPLICANT_EXCLUDE = re.compile(
    r"\b(pelnomocni\w*|inn\w*|wspol\w*|malzon\w*|dziecka|rodzic\w*|podmiot\w*|firm\w*|siedzib\w*|organ\w*|"
    r"urzad\w*|wlasciciel\w*|przedstawicie\w*|opiekun\w*|zmarl\w*|zagranic\w*|urzedu|instytucj\w*)\b"
)
# (wzorzec etykiety, atrybut MLPZ, read_only)
_MLPZ_RULES: list[tuple[re.Pattern[str], str, bool]] = [
    (re.compile(r"^(drugie imie|imie drugie|2 imie)$"), "secondName", True),
    (re.compile(r"^imi(e|ona)( .*)?$"), "name", True),
    (re.compile(r"^nazwisko$"), "surname", True),
    (re.compile(r"^(numer )?pesel$"), "pesel", True),
    (re.compile(r"^(numer )?(telefon\w*|tel)( .*)?$"), "phoneNumber", False),
    (re.compile(r"^(adres )?e ?-? ?mail( .*)?$"), "email", False),
    (re.compile(r"^kod pocztowy$"), "postCode", False),
    (re.compile(r"^ulica( .*)?$"), "street", False),
    (re.compile(r"^(numer|nr) (budynku|domu)( .*)?$"), "building", False),
    (re.compile(r"^(numer|nr) lokalu( .*)?$"), "apartment", False),
    (re.compile(r"^miejscowosc$"), "place", False),
    (re.compile(r"^gmina$"), "community", False),
]


def _mlpz_attr(f: DraftField) -> tuple[str, bool] | None:
    t = _words(f.title)
    for pat, attr, ro in _MLPZ_RULES:
        if pat.match(t):
            return attr, ro
    return None


def _apply_initial(fields: list[DraftField], path: list[str], used: set[tuple[tuple[str, ...], str]]) -> None:
    for f in fields:
        if f.type in ("SECTION", "REPEATING_SECTION"):
            _apply_initial(f.children, [*path, _words(f.title)], used)
        else:
            _initial_for_field(f, path, used)


def _in_applicant_section(path: list[str]) -> bool:
    if not path:
        return False
    joined = " | ".join(path)
    return bool(_APPLICANT_INCLUDE.search(path[-1])) and not _APPLICANT_EXCLUDE.search(joined)


def _initial_for_field(f: DraftField, path: list[str], used: set[tuple[tuple[str, ...], str]]) -> None:
    if f.type != "TEXT_FIELD" or f.default_value is not None or f.dictionary_name:
        return
    # adres krajowy (pokazywany dla kraju Polska) jest zasilany; warianty zagraniczne – nie
    if any(w.negate or _words(w.equals) != "polska" for w in f.show_when):
        return
    if not _in_applicant_section(path):
        return
    hit = _mlpz_attr(f)
    if hit is None:
        return
    attr, ro = hit
    if (tuple(path), attr) in used or _APPLICANT_EXCLUDE.search(_words(f.title)):
        return
    used.add((tuple(path), attr))
    f.default_value = f"MLPZ.{attr}"
    f.default_value_type = "EXTERNAL_SYSTEM"
    f.read_only = ro
    f.evidence = [
        *f.evidence,
        Evidence(
            by="dict",
            reason=f"pole danych zalogowanego użytkownika w sekcji wnioskodawcy – zasilane z MLPZ ({attr})",
        ),
    ]


# --- propozycje nowych słowników ----------------------------------------------------------------

_DOMAINS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\burzad\w* skarbow\w*\b"), "Urzędy skarbowe"),
    (re.compile(r"\brodzaj\w* dokument\w*\b"), "Rodzaje dokumentów"),
    (re.compile(r"\bstopien pokrewienstwa\b|\bstopnie pokrewienstwa\b"), "Stopnie pokrewieństwa"),
    (re.compile(r"\bstan cywilny\b"), "Stany cywilne"),
    (re.compile(r"\bsad (rejonowy|okregowy)\b"), "Sądy"),
    (re.compile(r"\bbank\b|\bnazwa banku\b"), "Banki"),
    (re.compile(r"\btytul\w* (prawn\w*|wlasnosci)\b|\bforma wlasnosci\b"), "Formy własności"),
]
_LONG_LIST = 8


def _title_name(title: str) -> str:
    t = re.sub(r"\s+", " ", title).strip(" :?.*")
    return (t[:1].upper() + t[1:]) if t else "Nowy słownik"


def _propose(draft: DraftForm) -> list[ProposedDict]:
    fields = [f for tab in draft.tabs for f in iter_draft(tab.fields)]
    cand = [f for f in fields if f.type in ("TEXT_FIELD", "SELECT", "RADIO", "CHECKBOX") and not f.dictionary_name]
    out: list[ProposedDict] = []
    names: set[str] = set()
    # powtórzone listy opcji (>=2 pola z tym samym zestawem >=3 opcji)
    sigs: dict[tuple[str, ...], list[DraftField]] = {}
    for f in cand:
        if len(f.options) >= 3:
            sigs.setdefault(tuple(sorted(_words(o.name) for o in f.options)), []).append(f)

    def add(f: DraftField, name: str, reason: str) -> None:
        if name in names or name in _load():
            return
        names.add(name)
        out.append(ProposedDict(name=name, field_key=f.key, items=[o.name for o in f.options], reason=reason))

    for f in cand:
        t = _words(f.title)
        dom = next((n for p, n in _DOMAINS if p.search(t)), None)
        if dom:
            add(
                f,
                dom,
                f"pole „{f.title}” dotyczy domeny, która nie ma słownika predefiniowanego – sugerowany nowy słownik",
            )
        elif len(f.options) >= _LONG_LIST:
            add(f, _title_name(f.title), f"długa lista ({len(f.options)} opcji) – warto wydzielić jako słownik")
        else:
            sig = tuple(sorted(_words(o.name) for o in f.options))
            if len(f.options) >= 3 and len(sigs.get(sig, [])) >= 2:
                add(f, _title_name(f.title), "ta sama lista opcji powtarza się w kilku polach – wspólny słownik")
    return out


def apply_dictionaries(draft: DraftForm) -> DictResult:
    d = draft.model_copy(deep=True)
    for tab in d.tabs:
        for f in iter_draft(tab.fields):
            _match_dictionary(f)
    used: set[tuple[tuple[str, ...], str]] = set()
    for tab in d.tabs:
        if tab.type == "MAIN":
            _apply_initial(tab.fields, [], used)
    return DictResult(draft=d, proposed=_propose(d))
