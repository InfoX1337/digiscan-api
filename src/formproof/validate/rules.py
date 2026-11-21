"""Reguły COI – każda wyprowadzona z materiałów (źródło w `Rule.source`).

Reguła zwraca listę problemów `(target, komunikat)`; pusty wynik = spełniona.
Severity: `error` – formularz nie zaimportuje się / łamie regułę obligatoryjną; `warning` – zalecenie (standardy).
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from functools import cache
from importlib import resources
from typing import Any, Literal

import jsonschema
from jsonata import Jsonata

from ..types.form import CONTAINER_TYPES, GRID_COLS, PRESENTATIONAL_TYPES, VALIDATORS, FormDefinition, iter_questions
from ..types.report import RuleResult
from .common import (
    CHOICE_TYPES,
    FINISH_ALLOWED,
    SRC_DICT,
    SRC_JSON,
    SRC_RT,
    SRC_SCHEMA,
    SRC_STD,
    TECH_NAME_RE,
    UUID_RE,
    containers,
    fold,
    has_input,
    walk,
)

Issue = tuple[str | None, str]
Severity = Literal["error", "warning", "info"]

TITLE_MAX = 255
SEARCH_THRESHOLD = 15
STATE_TYPES_FIELD: frozenset[str] = frozenset({"SHOW", "READ_ONLY"})
STATE_TYPES_SECTION: frozenset[str] = frozenset({"SHOW"})
# słowniki adresowe i Kraje – wyłącznie lista rozwijana (Hacknation – Słowniki)
SELECT_ONLY_DICT_RE = re.compile(r"kraj|teryt|wojew|powiat|gmin|miejscow")
# odwołania w JSONata: 'x' in field.techName / 'x' in fieldTechName / 'Strona' in title
REF_RE = re.compile(r"""(['"])([^'"]*)\1\s*in\s*(field\.techName|fieldTechName|title)\b""")

# walidator -> wzorzec etykiety (po fold()); ZIP_CODE nie dla adresów zagranicznych (standardy: „bez walidacji”)
LABEL_VALIDATORS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("PESEL", re.compile(r"\bpesel\b")),
    ("NIP", re.compile(r"\bnip\b")),
    ("REGON", re.compile(r"\bregon\b")),
    ("EMAIL", re.compile(r"\be-?mail\b")),
    ("ZIP_CODE", re.compile(r"\bkod pocztowy\b")),
)
FOREIGN_RE = re.compile(r"zagranic")


@dataclass(frozen=True)
class Rule:
    id: str
    title: str
    severity: Severity
    source: str
    check: Callable[[FormDefinition], list[Issue]]


def expected_validators(form: FormDefinition) -> dict[str, list[str]]:
    """field.id -> brakujące walidatory wynikające z etykiety (tylko TEXT_FIELD)."""
    out: dict[str, list[str]] = {}
    for n in walk(form):
        f = n.field
        if f.type != "TEXT_FIELD":
            continue
        label = fold(f.title)
        ctx = fold(f"{f.title} {f.tech_name} {n.parent.field.title if n.parent else ''}")
        missing = []
        for v, pat in LABEL_VALIDATORS:
            if v == "ZIP_CODE" and FOREIGN_RE.search(ctx):
                continue
            if pat.search(label) and v not in f.validation:
                missing.append(v)
        if missing:
            out[f.id] = missing
    return out


def allowed_validators(field_type: str) -> frozenset[str]:
    """Reguły techniczne: TEXT_FIELD – dowolny walidator; pozostałe pola wejściowe – tylko wymagalność."""
    if field_type == "TEXT_FIELD":
        return frozenset(VALIDATORS)
    if field_type in CONTAINER_TYPES or field_type in PRESENTATIONAL_TYPES or field_type == "CONSENT_SECTION":
        return frozenset()
    return frozenset({"REQUIRED"})


def jsonata_error(query: str) -> str | None:
    try:
        Jsonata(query)
    except Exception as e:  # JException i błędy parsera
        return str(e) or type(e).__name__
    return None


def jsonata_refs(query: str) -> list[tuple[str, str]]:
    """[(rodzaj, nazwa)] – rodzaj 'field' (techName) lub 'tab' (tytuł strony)."""
    return [("tab" if m.group(3) == "title" else "field", m.group(2)) for m in REF_RE.finditer(query)]


# ---------------------------------------------------------------- reguły


@cache
def _schema() -> dict[str, Any]:
    """schema.json COI z tolerancją: `repeatingSectionGrid` (przykłady COI) obok literówki `repetingSectionGrid`
    oraz `defaultValue` jako tablica (Reguły techniczne: SELECT/TEXTAREA/FILE_UPLOADER `"defaultValue": []`)."""
    raw = json.loads(resources.files(__package__).joinpath("data/schema.json").read_text(encoding="utf-8"))
    question = raw["properties"]["tabs"]["items"]["properties"]["questions"]["items"]
    props = question["properties"]["field"]["properties"]
    props["repeatingSectionGrid"] = {"type": "array", "items": {"$ref": "#/$defs/question"}}
    props["repetingSectionGrid"] = {"type": "array", "items": {"$ref": "#/$defs/question"}}
    props["defaultValue"] = {"type": ["string", "array"]}
    raw["$defs"] = {"question": question}
    return dict(raw)


def r_schema(form: FormDefinition) -> list[Issue]:
    v = jsonschema.Draft202012Validator(_schema())
    return [(None, f"/{'/'.join(map(str, e.absolute_path))}: {e.message}") for e in v.iter_errors(form.dump())]


def r_title(form: FormDefinition) -> list[Issue]:
    t = form.title.strip()
    if not t:
        return [(None, "brak tytułu formularza")]
    if len(form.title) > TITLE_MAX:
        return [(None, f"tytuł ma {len(form.title)} znaków (max {TITLE_MAX})")]
    return []


def r_min_tabs(form: FormDefinition) -> list[Issue]:
    return [] if len(form.tabs) >= 2 else [(None, f"liczba stron: {len(form.tabs)} (min. 2)")]


def r_finish(form: FormDefinition) -> list[Issue]:
    fin = [t for t in form.tabs if t.type == "FINISH"]
    if not fin:
        return [(None, "brak strony końcowej (FINISH)")]
    out: list[Issue] = []
    if len(fin) > 1:
        out += [(t.id, f"więcej niż jedna strona FINISH: {t.title!r}") for t in fin[:-1]]
    if form.tabs[-1].type != "FINISH":
        out.append((fin[-1].id, "strona FINISH nie jest ostatnia"))
    return out


def r_tab_nonempty(form: FormDefinition) -> list[Issue]:
    out: list[Issue] = []
    for t in form.tabs:
        if not any(q.field.type not in CONTAINER_TYPES for q in iter_questions(t.questions)):
            out.append((t.id, f"strona {t.title!r} nie zawiera żadnego pola"))
    return out


def r_in_section(form: FormDefinition) -> list[Issue]:
    return [
        (n.field.id, f"pole {n.field.tech_name!r} leży bezpośrednio na stronie, poza sekcją")
        for n in walk(form)
        if n.depth == 0 and n.field.type not in CONTAINER_TYPES
    ]


def r_no_nested_sections(form: FormDefinition) -> list[Issue]:
    return [
        (n.field.id, f"sekcja {n.field.tech_name!r} zagnieżdżona w sekcji")
        for n in walk(form)
        if n.depth > 0 and n.field.type in CONTAINER_TYPES
    ]


def r_finish_content(form: FormDefinition) -> list[Issue]:
    out: list[Issue] = []
    for n in walk(form):
        if form.tabs[n.tab_index].type == "FINISH" and n.field.type not in FINISH_ALLOWED:
            out.append((n.field.id, f"pole wejściowe {n.field.tech_name!r} ({n.field.type}) na stronie końcowej"))
    return out


def r_flow(form: FormDefinition) -> list[Issue]:
    ids = [t.id for t in form.tabs]
    known = set(ids)
    out: list[Issue] = []
    succ: dict[str, list[str]] = {i: [] for i in ids}
    for link in form.flow.links:
        if link.source not in known or link.target not in known:
            out.append((link.id, f"przejście {link.id} wskazuje nieistniejącą stronę"))
        elif link.source == link.target:
            out.append((link.id, f"przejście {link.id} prowadzi do tej samej strony"))
        else:
            succ[link.source].append(link.target)
    if not ids:
        return out
    seen = {ids[0]}
    stack = [ids[0]]
    while stack:
        for nxt in succ[stack.pop()]:
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    for t in form.tabs:
        if t.id not in seen:
            out.append((t.id, f"strona {t.title!r} nieosiągalna z pierwszej strony"))
        if t.type == "MAIN" and not succ[t.id]:
            out.append((t.id, f"strona {t.title!r} nie ma przejścia do kolejnej strony"))
        if t.type == "FINISH" and succ[t.id]:
            out.append((t.id, "strona końcowa ma przejście dalej"))
    return out


def r_uuid(form: FormDefinition) -> list[Issue]:
    ids = [("strona", t.id) for t in form.tabs]
    ids += [("pole", n.field.id) for n in walk(form)]
    ids += [("przejście", link.id) for link in form.flow.links]
    cnt = Counter(i for _, i in ids)
    out: list[Issue] = []
    reported: set[str] = set()
    for kind, i in ids:
        if i in reported:
            continue
        if not UUID_RE.match(i):
            out.append((i, f"{kind}: identyfikator {i!r} nie jest UUID"))
            reported.add(i)
        elif cnt[i] > 1:
            out.append((i, f"{kind}: identyfikator {i} powtórzony {cnt[i]}×"))
            reported.add(i)
    return out


def r_tech_unique(form: FormDefinition) -> list[Issue]:
    cnt = Counter(n.field.tech_name for n in walk(form))
    return [
        (n.field.id, f"techName {n.field.tech_name!r} powtórzony {cnt[n.field.tech_name]}×")
        for n in walk(form)
        if cnt[n.field.tech_name] > 1
    ]


def r_tech_format(form: FormDefinition) -> list[Issue]:
    return [
        (n.field.id, f"techName {n.field.tech_name!r} – dozwolone litery ASCII, cyfry i '_', start od litery")
        for n in walk(form)
        if not TECH_NAME_RE.match(n.field.tech_name)
    ]


def r_grid_bounds(form: FormDefinition) -> list[Issue]:
    out: list[Issue] = []
    for n in walk(form):
        q = n.question
        if q.x < 0 or q.y < 0 or q.rows < 1 or q.cols < 1 or q.x + q.cols > GRID_COLS:
            out.append((n.field.id, f"{n.field.tech_name!r}: x={q.x} y={q.y} rows={q.rows} cols={q.cols} poza siatką"))
    return out


def grid_overlaps(qs: list[Any]) -> list[int]:
    """Indeksy pytań, które nakładają się na wcześniejsze w tej samej siatce."""
    taken: set[tuple[int, int]] = set()
    bad: list[int] = []
    for i, q in enumerate(qs):
        cells = {(r, c) for r in range(q.y, q.y + max(q.rows, 1)) for c in range(q.x, q.x + max(q.cols, 1))}
        if cells & taken:
            bad.append(i)
        taken |= cells
    return bad


def r_grid_overlap(form: FormDefinition) -> list[Issue]:
    out: list[Issue] = []
    for _, qs in containers(form):
        for i in grid_overlaps(qs):
            f = qs[i].field
            out.append((f.id, f"{f.tech_name!r} nakłada się na inne pole (x={qs[i].x}, y={qs[i].y})"))
    return out


def r_choice_options(form: FormDefinition) -> list[Issue]:
    return [
        (n.field.id, f"{n.field.type} {n.field.tech_name!r} bez opcji i bez słownika (dictionaryName)")
        for n in walk(form)
        if n.field.type in CHOICE_TYPES and not n.field.options and not n.field.dictionary_name
    ]


def r_options_ok(form: FormDefinition) -> list[Issue]:
    out: list[Issue] = []
    for n in walk(form):
        f = n.field
        if f.options and f.type not in CHOICE_TYPES:
            out.append((f.id, f"{f.type} {f.tech_name!r} nie obsługuje opcji wyboru"))
        cnt = Counter(o.tech_name for o in f.options)
        for o in f.options:
            if not o.id or not o.name.strip():
                out.append((f.id, f"{f.tech_name!r}: opcja bez id lub nazwy"))
            elif not TECH_NAME_RE.match(o.tech_name):
                out.append((f.id, f"{f.tech_name!r}: opcja {o.name!r} ma niepoprawny techName {o.tech_name!r}"))
            elif cnt[o.tech_name] > 1:
                out.append((f.id, f"{f.tech_name!r}: powtórzony techName opcji {o.tech_name!r}"))
    return out


def r_dictionary(form: FormDefinition) -> list[Issue]:
    out: list[Issue] = []
    for n in walk(form):
        f = n.field
        if not f.dictionary_name:
            continue
        if f.type not in CHOICE_TYPES:
            out.append((f.id, f"słownik {f.dictionary_name!r} w polu typu {f.type} (dozwolone SELECT/RADIO/CHECKBOX)"))
        elif f.type != "SELECT" and SELECT_ONLY_DICT_RE.search(fold(f.dictionary_name)):
            out.append((f.id, f"słownik {f.dictionary_name!r} można przypisać wyłącznie do listy rozwijanej"))
    return out


def r_jsonata_syntax(form: FormDefinition) -> list[Issue]:
    out: list[Issue] = []
    for n in walk(form):
        for i, s in enumerate(n.field.states):
            err = jsonata_error(s.query) if s.query.strip() else "puste wyrażenie"
            if err:
                out.append((n.field.id, f"{n.field.tech_name!r} states[{i}]: {err}"))
    return out


def r_jsonata_refs(form: FormDefinition) -> list[Issue]:
    names = {n.field.tech_name for n in walk(form)}
    titles = {t.title for t in form.tabs}
    out: list[Issue] = []
    for n in walk(form):
        for i, s in enumerate(n.field.states):
            for kind, ref in jsonata_refs(s.query):
                if (kind == "field" and ref not in names) or (kind == "tab" and ref not in titles):
                    what = "pole" if kind == "field" else "stronę"
                    out.append(
                        (n.field.id, f"{n.field.tech_name!r} states[{i}] odwołuje się na nieistniejące {what} {ref!r}")
                    )
                elif kind == "field" and ref == n.field.tech_name:
                    out.append((n.field.id, f"{n.field.tech_name!r} states[{i}] zależy od samego siebie"))
    return out


def r_state_types(form: FormDefinition) -> list[Issue]:
    out: list[Issue] = []
    for n in walk(form):
        allowed = STATE_TYPES_SECTION if n.field.type in CONTAINER_TYPES else STATE_TYPES_FIELD
        for i, s in enumerate(n.field.states):
            if s.type not in allowed:
                out.append(
                    (n.field.id, f"{n.field.tech_name!r} states[{i}]: typ {s.type!r} (dozwolone {sorted(allowed)})")
                )
    return out


def r_section_title(form: FormDefinition) -> list[Issue]:
    return [
        (n.field.id, f"sekcja {n.field.tech_name!r} bez nazwy (title)")
        for n in walk(form)
        if n.field.type in CONTAINER_TYPES and not n.field.title.strip()
    ]


def r_info_description(form: FormDefinition) -> list[Issue]:
    return [
        (n.field.id, f"INFO_SECTION {n.field.tech_name!r} bez opisu (description)")
        for n in walk(form)
        if n.field.type == "INFO_SECTION" and not n.field.description.strip()
    ]


def r_consent(form: FormDefinition) -> list[Issue]:
    out: list[Issue] = []
    for n in walk(form):
        f = n.field
        if f.type == "CONSENT_SECTION":
            cfg = f.consent_section_config
            if cfg is None or not cfg.consents or any(not c.description.strip() for c in cfg.consents):
                out.append((f.id, f"sekcja zgód {f.tech_name!r} bez zdefiniowanych zgód (consents)"))
        elif f.consent_section_config is not None:
            out.append((f.id, f"consentSectionConfig dozwolone tylko dla CONSENT_SECTION ({f.tech_name!r})"))
    return out


def r_external_readonly(form: FormDefinition) -> list[Issue]:
    out: list[Issue] = []
    for n in walk(form):
        f = n.field
        if f.default_value_type == "EXTERNAL_SYSTEM":
            if not f.default_value:
                out.append((f.id, f"{f.tech_name!r}: EXTERNAL_SYSTEM bez wskazania źródła (defaultValue)"))
            elif not f.read_only:
                out.append((f.id, f"{f.tech_name!r}: dane z rejestru (EXTERNAL_SYSTEM) edytowalne – rozważ readOnly"))
    return out


def r_label_validators(form: FormDefinition) -> list[Issue]:
    return [
        (fid, f"brak walidatora {', '.join(v)} wynikającego z etykiety") for fid, v in expected_validators(form).items()
    ]


def r_validator_types(form: FormDefinition) -> list[Issue]:
    out: list[Issue] = []
    for n in walk(form):
        f = n.field
        allowed = allowed_validators(f.type)
        bad = [v for v in f.validation if v not in allowed]
        if bad:
            out.append((f.id, f"{f.type} {f.tech_name!r}: niedozwolone walidatory {bad}"))
        if len(set(f.validation)) != len(f.validation):
            out.append((f.id, f"{f.tech_name!r}: powtórzone walidatory"))
    return out


def r_tab_titles(form: FormDefinition) -> list[Issue]:
    cnt = Counter(t.title for t in form.tabs)
    out: list[Issue] = []
    for t in form.tabs:
        if not t.title.strip():
            out.append((t.id, "strona bez tytułu"))
        elif cnt[t.title] > 1:
            out.append((t.id, f"tytuł strony {t.title!r} niejednoznaczny (używany w JSONata: tabs['…' in title])"))
    return out


def r_search(form: FormDefinition) -> list[Issue]:
    return [
        (n.field.id, f"lista {n.field.tech_name!r} ma {len(n.field.options)} opcji – włącz wyszukiwarkę")
        for n in walk(form)
        if n.field.type == "SELECT" and len(n.field.options) > SEARCH_THRESHOLD and not n.field.search_enabled
    ]


def r_has_input(form: FormDefinition) -> list[Issue]:
    main = [t for t in form.tabs if t.type == "MAIN"]
    if main and not any(has_input(q) for t in main for q in t.questions):
        return [(None, "formularz nie zawiera żadnego pola do wypełnienia")]
    return []


RULES: tuple[Rule, ...] = (
    Rule("COI-R01", "Zgodność ze schematem JSON importu", "error", SRC_SCHEMA, r_schema),
    Rule("COI-R02", "Tytuł formularza (nazwa usługi) – wymagany, max 255 znaków", "error", SRC_RT, r_title),
    Rule("COI-R03", "Formularz zawiera minimum dwie strony", "error", SRC_RT, r_min_tabs),
    Rule("COI-R04", "Strona końcowa oznaczona FINISH (jedna, ostatnia), pozostałe MAIN", "error", SRC_RT, r_finish),
    Rule("COI-R05", "Każda strona zawiera minimum jedno pole", "error", SRC_RT, r_tab_nonempty),
    Rule("COI-R06", "Każde pole zagnieżdżone w sekcji lub sekcji powtarzającej się", "error", SRC_RT, r_in_section),
    Rule("COI-R07", "Brak zagnieżdżania sekcji w innej sekcji", "error", SRC_RT, r_no_nested_sections),
    Rule("COI-R08", "Na stronie końcowej brak pól typu Input", "error", SRC_RT, r_finish_content),
    Rule(
        "COI-R09", "Strony połączone warunkami przepływu (flow)", "error", f"{SRC_RT}; {SRC_JSON} (flow.links)", r_flow
    ),
    Rule("COI-R10", "Unikatowe identyfikatory UUID stron, pól i przejść", "error", SRC_JSON, r_uuid),
    Rule(
        "COI-R11",
        "Unikatowa nazwa techniczna pola (techName)",
        "error",
        f"{SRC_JSON} (techName → JSONata)",
        r_tech_unique,
    ),
    Rule(
        "COI-R12",
        "Poprawny format nazwy technicznej (ASCII, bez spacji)",
        "error",
        f"{SRC_JSON} (techName → JSONata)",
        r_tech_format,
    ),
    Rule(
        "COI-R13",
        "Pozycja pola mieści się w siatce (x, y, rows, cols)",
        "error",
        f"{SRC_JSON} (CSS grid-area)",
        r_grid_bounds,
    ),
    Rule("COI-R14", "Pola w siatce nie nakładają się", "error", f"{SRC_JSON} (CSS grid-area)", r_grid_overlap),
    Rule("COI-R15", "Pola wyboru mają opcje lub słownik", "error", SRC_RT, r_choice_options),
    Rule("COI-R16", "Opcje wyboru: id, nazwa i unikatowy techName", "error", f"{SRC_RT}; {SRC_JSON}", r_options_ok),
    Rule(
        "COI-R17",
        "Słownik tylko w polach SELECT/RADIO/CHECKBOX (adresowe i Kraje – SELECT)",
        "error",
        SRC_DICT,
        r_dictionary,
    ),
    Rule(
        "COI-R18",
        "Poprawna składnia wyrażeń JSONata w stanach pól",
        "error",
        f"{SRC_RT} (warunki jsonaty)",
        r_jsonata_syntax,
    ),
    Rule(
        "COI-R19",
        "Wyrażenia JSONata odwołują się do istniejących pól i stron",
        "error",
        f"{SRC_RT} (warunki jsonaty)",
        r_jsonata_refs,
    ),
    Rule(
        "COI-R20",
        "Dozwolone typy stanów: SHOW, READ_ONLY (sekcje: SHOW)",
        "error",
        f"{SRC_RT} (dynamiczne stany)",
        r_state_types,
    ),
    Rule("COI-R21", "Sekcja ma nazwę (title)", "error", f"{SRC_RT} (sekcja: title – TAK)", r_section_title),
    Rule(
        "COI-R22",
        "Sekcja informacyjna ma opis (description)",
        "error",
        f"{SRC_RT} (INFO_SECTION: description – TAK)",
        r_info_description,
    ),
    Rule("COI-R23", "Sekcja zgód zawiera zgody (consentSectionConfig)", "error", f"{SRC_RT}; {SRC_JSON}", r_consent),
    Rule(
        "COI-R24",
        "Dane z rejestru (EXTERNAL_SYSTEM) – źródło i tylko do odczytu",
        "warning",
        f"{SRC_JSON}; {SRC_STD} (Twoje dane)",
        r_external_readonly,
    ),
    Rule(
        "COI-R25",
        "Walidatory PESEL/NIP/REGON/e-mail/kod pocztowy zgodne z etykietą",
        "warning",
        f"{SRC_STD}; {SRC_RT} (walidatory)",
        r_label_validators,
    ),
    Rule(
        "COI-R26",
        "Walidatory dozwolone dla typu pola",
        "error",
        f"{SRC_RT} (specyfikacja komponentów)",
        r_validator_types,
    ),
    Rule(
        "COI-R27",
        "Strony mają niepusty, jednoznaczny tytuł",
        "error",
        f"{SRC_JSON}; {SRC_RT} (JSONata tabs[… in title])",
        r_tab_titles,
    ),
    Rule("COI-R28", "Lista rozwijana z >15 opcjami ma wyszukiwarkę", "warning", f"{SRC_STD} (pkt 4f)", r_search),
    Rule("COI-R29", "Formularz zawiera pola do wypełnienia", "warning", SRC_RT, r_has_input),
)
RULES_BY_ID: dict[str, Rule] = {r.id: r for r in RULES}

MAX_MSGS = 5


def evaluate(rule: Rule, form: FormDefinition, repaired: bool = False) -> RuleResult:
    issues = rule.check(form)
    targets = list(dict.fromkeys(t for t, _ in issues if t))
    if issues:
        msgs = [m for _, m in issues]
        more = f" (+{len(msgs) - MAX_MSGS})" if len(msgs) > MAX_MSGS else ""
        message = f"{'; '.join(msgs[:MAX_MSGS])}{more}. Źródło: {rule.source}"
    else:
        message = f"Spełniona. Źródło: {rule.source}"
    return RuleResult(
        id=rule.id,
        title=rule.title,
        severity=rule.severity,
        passed=not issues,
        repaired=repaired,
        targets=targets,
        message=message,
    )


def check_all(form: FormDefinition, repaired: set[str] | None = None) -> list[RuleResult]:
    rep = repaired or set()
    return [evaluate(r, form, r.id in rep) for r in RULES]
