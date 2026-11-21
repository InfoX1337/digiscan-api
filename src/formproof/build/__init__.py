"""BUILD (I2): DraftForm -> FormDefinition.

UUID deterministyczne (uuid5 z tytułu formularza i ścieżki), techName ASCII unikalny w formularzu,
siatka jednokolumnowa (standard COI: układ jednokolumnowy, x=0, cols=3), flow liniowe, stany SHOW w JSONata.
"""

from __future__ import annotations

from ..types.draft import DraftField, DraftForm
from ..types.form import (
    CONTAINER_TYPES,
    GRID_COLS,
    FieldOption,
    FieldState,
    Flow,
    FlowLink,
    FormDefinition,
    FormField,
    Question,
    Tab,
)
from ..types.stages import BuildResult
from ..validate.common import new_id, slugify, unique_name

INPUT_TYPES = frozenset({"SELECT", "RADIO", "CHECKBOX"})


def _q(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _sq(s: str) -> str:
    return s.replace("'", "\\'")


class _Ctx:
    def __init__(self, title: str) -> None:
        self.title = title
        self.taken: set[str] = set()
        self.key_to_id: dict[str, str] = {}
        self.path: dict[str, tuple[str, str | None, str]] = {}  # key -> (tab title, section techName, techName)

    def tech(self, title: str, fallback: str) -> str:
        name = unique_name(slugify(title, fallback), self.taken)
        self.taken.add(name)
        return name


def _ref(ctx: _Ctx, key: str) -> str | None:
    p = ctx.path.get(key)
    if not p:
        return None
    tab, sec, tech = p
    base = f"tabs['{_sq(tab)}' in title].questions"
    if sec is None:
        return f"{base}['{tech}' in field.techName].field.__userAnswer"
    return (
        f"{base}['{sec}' in field.techName].field.repeatingSectionGrid['{tech}' in field.techName].field.__userAnswer"
    )


def _states(ctx: _Ctx, f: DraftField) -> list[FieldState]:
    out = [FieldState(type=s.type, query=s.query) for s in f.states]
    for w in f.show_when:
        ref = _ref(ctx, w.when_key)
        if ref is None:
            continue
        cond = f'("{_q(w.equals)}" in {ref})'
        out.append(FieldState(type="SHOW", query=f"$not{cond}" if w.negate else cond))
    return out


def _field(ctx: _Ctx, f: DraftField, order: int, children: list[Question]) -> FormField:
    fid = new_id(ctx.title, "field", f.key)
    ctx.key_to_id[f.key] = fid
    tech = ctx.path[f.key][2]
    opts: list[FieldOption] = []
    if f.type in INPUT_TYPES and not f.dictionary_name:
        seen: set[str] = set()
        for o in f.options:
            otech = unique_name(slugify(o.name, "opcja"), seen)
            seen.add(otech)
            opts.append(FieldOption(id=new_id(ctx.title, "opt", f.key, otech), name=o.name, techName=otech))
    dv = f.default_value
    if f.type == "SELECT" and isinstance(dv, str):
        dv = [dv]
    return FormField(
        id=fid,
        type=f.type,
        techName=tech,
        title=f.title,
        description=f.description or "",
        options=opts,
        validation=list(dict.fromkeys(f.validation)),
        readOnly=f.read_only or f.default_value_type == "EXTERNAL_SYSTEM",
        repeatingSectionGrid=children,
        states=_states(ctx, f),
        questionOrder=order,
        tooltipMessage=f.tooltip_message or "",
        dictionaryName=f.dictionary_name,
        multiLevelTree=f.multi_level_tree,
        searchEnabled=True if f.dictionary_name or len(opts) > 15 else None,
        defaultValue=dv,
        defaultValueType=f.default_value_type,
        consentSectionConfig=f.consent_section_config,
    )


def build(draft: DraftForm) -> BuildResult:
    ctx = _Ctx(draft.title)
    # 1) nazwy techniczne i ścieżki (potrzebne do JSONata, zanim zbudujemy stany)
    for t in draft.tabs:
        for top in t.fields:
            st = ctx.tech(top.title, "sekcja")
            ctx.path[top.key] = (t.title, None, st)
            for c in top.children:
                ctx.path[c.key] = (t.title, st, ctx.tech(c.title or c.type.lower(), c.type.lower()))
    # 2) struktura: sekcje w kolejnych wierszach, pola w jednej kolumnie
    tabs: list[Tab] = []
    for ti, t in enumerate(draft.tabs):
        qs: list[Question] = []
        y = 0
        for si, top in enumerate(t.fields):
            if top.type in CONTAINER_TYPES:
                kids = [
                    Question(x=0, y=ci, rows=1, cols=GRID_COLS, field=_field(ctx, c, ci, []))
                    for ci, c in enumerate(top.children)
                ]
                rows = len(kids) + 1
            else:
                kids, rows = [], 1
            qs.append(Question(x=0, y=y, rows=rows, cols=GRID_COLS, field=_field(ctx, top, si, kids)))
            y += rows
        tabs.append(Tab(id=new_id(ctx.title, "tab", str(ti), t.title), title=t.title, type=t.type, questions=qs))
    links = [
        FlowLink(id=new_id(ctx.title, "flow", a.id, b.id), source=a.id, target=b.id)
        for a, b in zip(tabs, tabs[1:], strict=False)
    ]
    form = FormDefinition(title=draft.title[:255], tabs=tabs, flow=Flow(links=links))
    return BuildResult(form=form, key_to_id=ctx.key_to_id)
