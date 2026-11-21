"""Auto-naprawa: modyfikuje KOPIĘ formularza i zwraca listę `Repair` (reguła, JSON Pointer, przed/po).

Każda funkcja jest idempotentna – gdy reguła jest spełniona, nic nie zmienia.
Świadomie bez naprawy: R01, R02 (pusty tytuł), R15 SELECT/RADIO bez opcji, R24 (readOnly to decyzja merytoryczna:
w przykładach COI część danych z rejestru jest edytowalna), R29.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from ..types.form import (
    CONTAINER_TYPES,
    GRID_COLS,
    ConsentSectionConfig,
    FieldOption,
    FieldState,
    Flow,
    FormDefinition,
    FormField,
    Question,
    Tab,
    iter_questions,
)
from ..types.report import Repair
from . import rules as R
from .common import (
    CHOICE_TYPES,
    FINISH_ALLOWED,
    TECH_NAME_RE,
    UUID_RE,
    containers,
    fold,
    new_id,
    slugify,
    unique_name,
    walk,
)

RepairFn = Callable[[FormDefinition], list[Repair]]


def _field(data: dict[str, Any]) -> FormField:
    return FormField.model_validate(data)


def _question(y: int, rows: int, field: FormField) -> Question:
    return Question.model_validate({"x": 0, "y": y, "rows": rows, "cols": GRID_COLS, "field": field})


def _all_names(form: FormDefinition) -> set[str]:
    return {n.field.tech_name for n in walk(form)}


def _rename_refs(form: FormDefinition, old: str, new: str) -> None:
    """Aktualizuje odwołania `'old' in field.techName` w JSONata po zmianie techName."""
    pat = re.compile(r"""(['"])""" + re.escape(old) + r"""\1(\s*in\s*(?:field\.techName|fieldTechName)\b)""")
    for n in walk(form):
        for s in n.field.states:
            s.query = pat.sub(lambda m: f"{m.group(1)}{new}{m.group(1)}{m.group(2)}", s.query)


def _bottom(qs: list[Question]) -> int:
    return max((q.y + max(q.rows, 1) for q in qs), default=0)


# ---------------------------------------------------------------- identyfikatory i nazwy


def fix_uuid(form: FormDefinition) -> list[Repair]:
    out: list[Repair] = []
    seen: set[str] = set()

    def fresh(kind: str, old: str, path: str) -> str | None:
        if UUID_RE.match(old) and old not in seen:
            seen.add(old)
            return None
        new = new_id(kind, path, old)
        seen.add(new)
        out.append(
            Repair(rule_id="COI-R10", path=f"{path}/id", description=f"Nowy UUID ({kind})", before=old, after=new)
        )
        return new

    for ti, t in enumerate(form.tabs):
        new = fresh("tab", t.id, f"/tabs/{ti}")
        if new:
            # przejścia wskazujące stary id – przepinamy tylko gdy id był unikatowy (inaczej flow przebuduje R09)
            if sum(1 for x in form.tabs if x.id == t.id) == 1:
                for link in form.flow.links:
                    link.source = new if link.source == t.id else link.source
                    link.target = new if link.target == t.id else link.target
            t.id = new
    for n in walk(form):
        new = fresh("field", n.field.id, f"{n.path}/field")
        if new:
            n.field.id = new
    for li, link in enumerate(form.flow.links):
        new = fresh("link", link.id, f"/flow/links/{li}")
        if new:
            link.id = new
    return out


def fix_tech_format(form: FormDefinition) -> list[Repair]:
    out: list[Repair] = []
    for n in walk(form):
        f = n.field
        if TECH_NAME_RE.match(f.tech_name):
            continue
        taken = _all_names(form) - {f.tech_name}
        new = unique_name(slugify(f.tech_name or f.title, fallback=f.type.lower()), taken)
        old = f.tech_name
        if old:
            _rename_refs(form, old, new)
        f.tech_name = new
        out.append(
            Repair(
                rule_id="COI-R12", path=f"{n.path}/field/techName", description="Slug techName", before=old, after=new
            )
        )
    return out


def fix_tech_unique(form: FormDefinition) -> list[Repair]:
    out: list[Repair] = []
    seen: set[str] = set()
    names = [n.field.tech_name for n in walk(form)]
    for n in walk(form):
        f = n.field
        if f.tech_name in seen:
            new = unique_name(f.tech_name, set(names) | seen)
            out.append(
                Repair(
                    rule_id="COI-R11",
                    path=f"{n.path}/field/techName",
                    description="Deduplikacja techName",
                    before=f.tech_name,
                    after=new,
                )
            )
            f.tech_name = new
        seen.add(f.tech_name)
    return out


def fix_options(form: FormDefinition) -> list[Repair]:
    out: list[Repair] = []
    for n in walk(form):
        f = n.field
        if not f.options:
            continue
        before = [o.dump() for o in f.options]
        seen: set[str] = set()
        kept = []
        for o in f.options:
            if not o.name.strip():
                continue
            if not o.id:
                o.id = o.name
            if not TECH_NAME_RE.match(o.tech_name):
                o.tech_name = slugify(o.tech_name or o.name, fallback="opcja")
            o.tech_name = unique_name(o.tech_name, seen)
            seen.add(o.tech_name)
            kept.append(o)
        after = [o.dump() for o in kept]
        if after != before:
            f.options = kept
            out.append(
                Repair(
                    rule_id="COI-R16",
                    path=f"{n.path}/field/options",
                    description="Poprawa opcji wyboru",
                    before=before,
                    after=after,
                )
            )
    return out


def fix_tab_titles(form: FormDefinition) -> list[Repair]:
    out: list[Repair] = []
    seen: set[str] = set()
    for ti, t in enumerate(form.tabs):
        title = t.title.strip() or ("Strona końcowa" if t.type == "FINISH" else f"Strona {ti + 1}")
        base, i = title, 2
        while title in seen:
            title, i = f"{base} ({i})", i + 1
        seen.add(title)
        if title != t.title:
            out.append(
                Repair(
                    rule_id="COI-R27", path=f"/tabs/{ti}/title", description="Tytuł strony", before=t.title, after=title
                )
            )
            t.title = title
    return out


# ---------------------------------------------------------------- struktura


def fix_section_title(form: FormDefinition) -> list[Repair]:
    out: list[Repair] = []
    for n in walk(form):
        f = n.field
        if f.type in CONTAINER_TYPES and not f.title.strip():
            new = f.tech_name.replace("_", " ").strip().capitalize() or "Sekcja"
            out.append(
                Repair(
                    rule_id="COI-R21",
                    path=f"{n.path}/field/title",
                    description="Nazwa sekcji z techName",
                    before=f.title,
                    after=new,
                )
            )
            f.title = new
    return out


def fix_info_description(form: FormDefinition) -> list[Repair]:
    out: list[Repair] = []
    for n in walk(form):
        f = n.field
        if f.type == "INFO_SECTION" and not f.description.strip() and f.title.strip():
            out.append(
                Repair(
                    rule_id="COI-R22",
                    path=f"{n.path}/field/description",
                    description="Opis z tytułu",
                    before=f.description,
                    after=f.title,
                )
            )
            f.description = f.title
    return out


def fix_consent(form: FormDefinition) -> list[Repair]:
    out: list[Repair] = []
    for n in walk(form):
        f = n.field
        if f.type != "CONSENT_SECTION" and f.consent_section_config is not None:
            out.append(
                Repair(
                    rule_id="COI-R23",
                    path=f"{n.path}/field/consentSectionConfig",
                    description="Usunięto konfigurację zgód",
                    before=f.consent_section_config.model_dump(),
                    after=None,
                )
            )
            f.consent_section_config = None
        if f.type != "CONSENT_SECTION":
            continue
        cfg = f.consent_section_config
        text = (f.description or f.title).strip()
        if (cfg is None or not cfg.consents) and text:
            before = cfg.model_dump() if cfg else None
            f.consent_section_config = ConsentSectionConfig.model_validate(
                {"consents": [{"description": text}], "required": True}
            )
            out.append(
                Repair(
                    rule_id="COI-R23",
                    path=f"{n.path}/field/consentSectionConfig",
                    description="Zgoda z opisu pola",
                    before=before,
                    after=f.consent_section_config.model_dump(),
                )
            )
    return out


def _wrap(form: FormDefinition, ti: int, run: list[Question], taken: set[str]) -> tuple[Question, Repair]:
    tab = form.tabs[ti]
    tech = unique_name(f"{slugify(tab.title, fallback='strona')}_sekcja", taken)
    y0 = min(q.y for q in run)
    children = sorted(run, key=lambda q: (q.y, q.x))
    for q in children:
        q.y -= y0
    sec = _field(
        {
            "id": new_id("section", tab.id, tech),
            "type": "SECTION",
            "techName": tech,
            "title": tab.title or "Sekcja",
            "repeatingSectionGrid": [c.dump() for c in children],
        }
    )
    rep = Repair(
        rule_id="COI-R06",
        path=f"/tabs/{ti}/questions",
        description=f"Pola {[q.field.tech_name for q in run]} owinięte w sekcję {tech!r}",
        before=None,
        after=tech,
    )
    return _question(y0, max(_bottom(children), 1), sec), rep


def fix_in_section(form: FormDefinition) -> list[Repair]:
    """Pola luzem na stronie → owinięte w nową sekcję (kolejne pola razem)."""
    out: list[Repair] = []
    for ti, tab in enumerate(form.tabs):
        if all(q.field.type in CONTAINER_TYPES for q in tab.questions):
            continue
        result: list[Question] = []
        run: list[Question] = []
        for q in [*tab.questions, None]:
            if q is not None and q.field.type not in CONTAINER_TYPES:
                run.append(q)
                continue
            if run:
                taken = _all_names(form) | {x.field.tech_name for x in result}
                sec, rep = _wrap(form, ti, run, taken)
                result.append(sec)
                out.append(rep)
                run = []
            if q is not None:
                result.append(q)
        tab.questions = result
    return out


def fix_nested_sections(form: FormDefinition) -> list[Repair]:
    """Sekcja w sekcji → przeniesiona na poziom strony, zaraz pod rodzica."""
    out: list[Repair] = []
    for ti, tab in enumerate(form.tabs):
        result: list[Question] = []
        for q in tab.questions:
            result.append(q)
            pending = [q]
            while pending:
                parent = pending.pop(0)
                nested = [c for c in parent.field.repeating_section_grid if c.field.type in CONTAINER_TYPES]
                if not nested:
                    continue
                parent.field.repeating_section_grid = [
                    c for c in parent.field.repeating_section_grid if c not in nested
                ]
                for c in nested:
                    out.append(
                        Repair(
                            rule_id="COI-R07",
                            path=f"/tabs/{ti}/questions",
                            description=f"Sekcja {c.field.tech_name!r} wyjęta z {parent.field.tech_name!r} na stronę",
                            before=parent.field.tech_name,
                            after=None,
                        )
                    )
                    c.x, c.cols = 0, GRID_COLS
                    result.append(c)
                    pending.append(c)
        tab.questions = result
    return out


def fix_finish_content(form: FormDefinition) -> list[Repair]:
    """Pola wejściowe ze strony końcowej → przeniesione na ostatnią stronę MAIN."""
    out: list[Repair] = []
    for ti, tab in enumerate(form.tabs):
        if tab.type != "FINISH":
            continue
        bad = [q for q in tab.questions if any(x.field.type not in FINISH_ALLOWED for x in iter_questions([q]))]
        if not bad:
            continue
        mains = [t for t in form.tabs if t.type == "MAIN"]
        if not mains:
            out.append(
                Repair(
                    rule_id="COI-R08",
                    path=f"/tabs/{ti}/type",
                    description="Strona z polami wejściowymi zmieniona na MAIN",
                    before="FINISH",
                    after="MAIN",
                )
            )
            tab.type = "MAIN"
            continue
        target = mains[-1]
        for q in bad:
            tab.questions.remove(q)
            q.y = _bottom(target.questions)
            target.questions.append(q)
            out.append(
                Repair(
                    rule_id="COI-R08",
                    path=f"/tabs/{ti}/questions",
                    description=f"{q.field.tech_name!r} przeniesione na stronę {target.title!r}",
                    before=tab.title,
                    after=target.title,
                )
            )
    return out


def _finish_tab(form: FormDefinition) -> Tab:
    names = _all_names(form)
    sec = unique_name("podsumowanie", names)
    info = unique_name("podsumowanie_info", names | {sec})
    info_f = _field(
        {
            "id": new_id("finish-info", form.title),
            "type": "INFO_SECTION",
            "techName": info,
            "title": "",
            "description": "Sprawdź poprawność wprowadzonych danych przed wysłaniem wniosku.",
        }
    )
    sec_f = _field(
        {
            "id": new_id("finish-section", form.title),
            "type": "SECTION",
            "techName": sec,
            "title": "Podsumowanie",
            "repeatingSectionGrid": [_question(0, 1, info_f).dump()],
        }
    )
    return Tab.model_validate(
        {
            "id": new_id("finish-tab", form.title),
            "title": "Strona końcowa",
            "type": "FINISH",
            "questions": [_question(0, 2, sec_f).dump()],
        }
    )


def fix_finish(form: FormDefinition) -> list[Repair]:
    out: list[Repair] = []
    fin = [t for t in form.tabs if t.type == "FINISH"]
    if not fin:
        tab = _finish_tab(form)
        form.tabs.append(tab)
        out.append(
            Repair(
                rule_id="COI-R04",
                path=f"/tabs/{len(form.tabs) - 1}",
                description="Dodano stronę końcową FINISH",
                before=None,
                after=tab.title,
            )
        )
        return out
    keep = fin[-1]
    for t in fin[:-1]:
        out.append(
            Repair(
                rule_id="COI-R04",
                path=f"/tabs/{form.tabs.index(t)}/type",
                description="Nadmiarowa strona FINISH → MAIN",
                before="FINISH",
                after="MAIN",
            )
        )
        t.type = "MAIN"
    if form.tabs[-1] is not keep:
        i = form.tabs.index(keep)
        form.tabs.remove(keep)
        form.tabs.append(keep)
        out.append(
            Repair(
                rule_id="COI-R04",
                path=f"/tabs/{i}",
                description="Strona FINISH przeniesiona na koniec",
                before=i,
                after=len(form.tabs) - 1,
            )
        )
    return out


def fix_tab_nonempty(form: FormDefinition) -> list[Repair]:
    out: list[Repair] = []
    for t in list(form.tabs):
        if any(q.field.type not in CONTAINER_TYPES for q in iter_questions(t.questions)):
            continue
        i = form.tabs.index(t)
        if t.type == "FINISH":
            t.questions = _finish_tab(form).questions
            out.append(
                Repair(
                    rule_id="COI-R05",
                    path=f"/tabs/{i}/questions",
                    description="Uzupełniono pustą stronę końcową",
                    before=None,
                    after="podsumowanie",
                )
            )
        elif sum(1 for x in form.tabs if x.type == "MAIN") > 1:
            form.tabs.remove(t)
            out.append(
                Repair(
                    rule_id="COI-R05",
                    path=f"/tabs/{i}",
                    description="Usunięto pustą stronę",
                    before=t.title,
                    after=None,
                )
            )
    return out


def fix_flow(form: FormDefinition) -> list[Repair]:
    if not R.r_flow(form):
        return []
    before = [link.dump() for link in form.flow.links]
    links = [
        {"id": new_id("link", a.id, b.id), "source": a.id, "target": b.id}
        for a, b in zip(form.tabs, form.tabs[1:], strict=False)
    ]
    form.flow = Flow.model_validate({"links": links})
    return [
        Repair(
            rule_id="COI-R09",
            path="/flow/links",
            description="Przebudowano liniowy przepływ stron",
            before=before,
            after=links,
        )
    ]


# ---------------------------------------------------------------- siatka


def fix_grid(form: FormDefinition) -> list[Repair]:
    """Siatka z błędem (poza zakresem / nakładanie) → układ jednokolumnowy (standardy: pkt 2), kolejność wg (y, x)."""
    out: list[Repair] = []
    for path, qs in list(containers(form)):
        bounds = any(q.x < 0 or q.y < 0 or q.rows < 1 or q.cols < 1 or q.x + q.cols > GRID_COLS for q in qs)
        overlap = bool(R.grid_overlaps(qs))
        if not bounds and not overlap:
            continue
        before = [(q.field.tech_name, q.x, q.y, q.rows, q.cols) for q in qs]
        y = 0
        for q in sorted(qs, key=lambda q: (q.y, q.x)):
            q.x, q.cols, q.rows, q.y = 0, GRID_COLS, max(q.rows, 1), y
            y += q.rows
        after = [(q.field.tech_name, q.x, q.y, q.rows, q.cols) for q in qs]
        for rule_id, hit in (("COI-R13", bounds), ("COI-R14", overlap)):
            if hit:
                desc = "Przeliczono siatkę (jedna kolumna, bez nakładania)"
                out.append(Repair(rule_id=rule_id, path=path, description=desc, before=before, after=after))
    return out


# ---------------------------------------------------------------- pola


def fix_choice_options(form: FormDefinition) -> list[Repair]:
    out: list[Repair] = []
    for n in walk(form):
        f = n.field
        if f.type == "CHECKBOX" and not f.options and not f.dictionary_name and f.title.strip():
            opt = {"id": f.title.strip(), "name": f.title.strip(), "techName": slugify(f.title, fallback="opcja")}
            f.options = [FieldOption.model_validate(opt)]
            out.append(
                Repair(
                    rule_id="COI-R15",
                    path=f"{n.path}/field/options",
                    description="Pojedynczy checkbox – opcja z etykiety",
                    before=[],
                    after=[opt],
                )
            )
    return out


def fix_dictionary(form: FormDefinition) -> list[Repair]:
    out: list[Repair] = []
    for n in walk(form):
        f = n.field
        if not f.dictionary_name:
            continue
        if f.type not in CHOICE_TYPES or (f.type != "SELECT" and R.SELECT_ONLY_DICT_RE.search(fold(f.dictionary_name))):
            out.append(
                Repair(
                    rule_id="COI-R17",
                    path=f"{n.path}/field/type",
                    description=f"Pole ze słownikiem {f.dictionary_name!r} → lista rozwijana",
                    before=f.type,
                    after="SELECT",
                )
            )
            f.type = "SELECT"
    return out


def fix_state_types(form: FormDefinition) -> list[Repair]:
    out: list[Repair] = []
    for n in walk(form):
        for i, s in enumerate(n.field.states):
            if s.type == "HIDE":
                before = s.dump()
                s.type, s.query = "SHOW", f"$not({s.query})"
                out.append(
                    Repair(
                        rule_id="COI-R20",
                        path=f"{n.path}/field/states/{i}",
                        description="HIDE → SHOW z zanegowanym warunkiem",
                        before=before,
                        after=s.dump(),
                    )
                )
    return out


def _balance(query: str) -> str | None:
    q = query.strip()
    for o, c in (("(", ")"), ("[", "]"), ("{", "}")):
        diff = q.count(o) - q.count(c)
        q = q + c * diff if diff > 0 else q
    return q if q != query.strip() and R.jsonata_error(q) is None else None


def fix_jsonata_syntax(form: FormDefinition) -> list[Repair]:
    """Niezamknięte nawiasy → domknięte; inaczej stan usunięty (pole zawsze widoczne – do przeglądu)."""
    out: list[Repair] = []
    for n in walk(form):
        kept: list[FieldState] = []
        for i, s in enumerate(n.field.states):
            if s.query.strip() and R.jsonata_error(s.query) is None:
                kept.append(s)
                continue
            fixed = _balance(s.query) if s.query.strip() else None
            path = f"{n.path}/field/states/{i}"
            if fixed:
                out.append(
                    Repair(
                        rule_id="COI-R18",
                        path=f"{path}/query",
                        description="Domknięto nawiasy w JSONata",
                        before=s.query,
                        after=fixed,
                    )
                )
                s.query = fixed
                kept.append(s)
            else:
                out.append(
                    Repair(
                        rule_id="COI-R18",
                        path=path,
                        description="Usunięto niepoprawny stan JSONata",
                        before=s.dump(),
                        after=None,
                    )
                )
        n.field.states = kept
    return out


def fix_jsonata_refs(form: FormDefinition) -> list[Repair]:
    """Stan odwołujący się do nieistniejącego pola/strony nigdy się nie spełni → usunięty."""
    names = _all_names(form)
    titles = {t.title for t in form.tabs}
    out: list[Repair] = []
    for n in walk(form):
        kept: list[FieldState] = []
        for i, s in enumerate(n.field.states):
            refs = R.jsonata_refs(s.query)
            bad = [
                r
                for k, r in refs
                if (k == "field" and (r not in names or r == n.field.tech_name)) or (k == "tab" and r not in titles)
            ]
            if bad:
                out.append(
                    Repair(
                        rule_id="COI-R19",
                        path=f"{n.path}/field/states/{i}",
                        description=f"Usunięto stan z odwołaniem do {bad}",
                        before=s.dump(),
                        after=None,
                    )
                )
            else:
                kept.append(s)
        n.field.states = kept
    return out


def fix_label_validators(form: FormDefinition) -> list[Repair]:
    missing = R.expected_validators(form)
    out: list[Repair] = []
    for n in walk(form):
        if n.field.id in missing:
            before = list(n.field.validation)
            n.field.validation = [*before, *missing[n.field.id]]  # type: ignore[list-item]
            out.append(
                Repair(
                    rule_id="COI-R25",
                    path=f"{n.path}/field/validation",
                    description="Walidator wg etykiety",
                    before=before,
                    after=list(n.field.validation),
                )
            )
    return out


def fix_validator_types(form: FormDefinition) -> list[Repair]:
    out: list[Repair] = []
    for n in walk(form):
        f = n.field
        allowed = R.allowed_validators(f.type)
        new = list(dict.fromkeys(v for v in f.validation if v in allowed))
        if new != f.validation:
            out.append(
                Repair(
                    rule_id="COI-R26",
                    path=f"{n.path}/field/validation",
                    description="Usunięto niedozwolone/powtórzone walidatory",
                    before=list(f.validation),
                    after=new,
                )
            )
            f.validation = new
    return out


def fix_search(form: FormDefinition) -> list[Repair]:
    out: list[Repair] = []
    for n in walk(form):
        f = n.field
        if f.type == "SELECT" and len(f.options) > R.SEARCH_THRESHOLD and not f.search_enabled:
            out.append(
                Repair(
                    rule_id="COI-R28",
                    path=f"{n.path}/field/searchEnabled",
                    description="Włączono wyszukiwarkę",
                    before=f.search_enabled,
                    after=True,
                )
            )
            f.search_enabled = True
    return out


def fix_title(form: FormDefinition) -> list[Repair]:
    if len(form.title) <= R.TITLE_MAX:
        return []
    cut = form.title[: R.TITLE_MAX]
    if " " in cut:
        cut = cut[: cut.rfind(" ")]
    new = cut.rstrip(" ,;:-")
    out = [
        Repair(
            rule_id="COI-R02", path="/title", description="Skrócono tytuł do 255 znaków", before=form.title, after=new
        )
    ]
    form.title = new
    return out


# Kolejność ma znaczenie: najpierw tożsamość i struktura, potem siatka i JSONata, na końcu flow.
REPAIRS: tuple[RepairFn, ...] = (
    fix_uuid,
    fix_tech_format,
    fix_tech_unique,
    fix_options,
    fix_tab_titles,
    fix_section_title,
    fix_info_description,
    fix_consent,
    fix_nested_sections,
    fix_in_section,
    fix_finish_content,
    fix_finish,
    fix_tab_nonempty,
    fix_grid,
    fix_choice_options,
    fix_dictionary,
    fix_state_types,
    fix_jsonata_syntax,
    fix_jsonata_refs,
    fix_validator_types,
    fix_label_validators,
    fix_search,
    fix_title,
    fix_flow,
)


def repair_all(form: FormDefinition) -> list[Repair]:
    out: list[Repair] = []
    for fn in REPAIRS:
        out += fn(form)
    return out
