from __future__ import annotations

import copy
import json
from collections.abc import Callable
from typing import Any

import pytest

from formproof.types.form import FormDefinition, iter_questions
from formproof.validate import RULES, validate

from ..conftest import FIXTURES

# expected1 (wzorcowy przykład COI) ma udokumentowane ostrzeżenia:
# R24 – dane z rejestru (EXTERNAL_SYSTEM) edytowalne; R25 – brak walidatorów NIP/REGON/ZIP_CODE/EMAIL wg etykiety.
EXPECTED1_WARNINGS = {"COI-R24", "COI-R25"}


@pytest.fixture(scope="module")
def raw() -> dict[str, Any]:
    return dict(json.loads((FIXTURES / "expected1.json").read_text()))


def _form(raw: dict[str, Any], mutate: Callable[[dict[str, Any]], None] | None = None) -> FormDefinition:
    d = copy.deepcopy(raw)
    if mutate:
        mutate(d)
    return FormDefinition.model_validate(d)


def _failed(form: FormDefinition, repair: bool) -> dict[str, str]:
    return {r.id: r.severity for r in validate(form, repair=repair).rules if not r.passed}


def _sec(d: dict[str, Any], tab: int = 0, q: int = 0) -> list[dict[str, Any]]:
    grid: list[dict[str, Any]] = d["tabs"][tab]["questions"][q]["field"]["repeatingSectionGrid"]
    return grid


def test_rules_catalog() -> None:
    assert len(RULES) >= 12
    assert len({r.id for r in RULES}) == len(RULES)
    assert all(r.id.startswith("COI-R") and r.title and r.source for r in RULES)


def test_expected1_has_no_errors(raw: dict[str, Any]) -> None:
    res = validate(_form(raw), repair=False)
    assert len(res.rules) == len(RULES)
    failed = {r.id: r for r in res.rules if not r.passed}
    assert set(failed) <= EXPECTED1_WARNINGS
    assert all(r.severity == "warning" for r in failed.values())
    assert res.repairs == []
    for r in res.rules:
        assert r.message and "Źródło:" in r.message


def test_does_not_mutate_input(raw: dict[str, Any]) -> None:
    form = _form(raw, lambda d: d["tabs"].pop())
    before = form.dump()
    res = validate(form, repair=True)
    assert form.dump() == before
    assert res.form is not form
    assert len(res.form.tabs) == len(form.tabs) + 1


def test_expected1_repair_only_adds_validators(raw: dict[str, Any]) -> None:
    res = validate(_form(raw), repair=True)
    assert {r.rule_id for r in res.repairs} == {"COI-R25"}
    assert "COI-R25" not in _failed(res.form, repair=False)
    nip = next(q.field for t in res.form.tabs for q in iter_questions(t.questions) if q.field.tech_name == "nip")
    assert "NIP" in nip.validation
    # ZIP_CODE nie dla adresu zagranicznego (standardy: „kod pocztowy bez walidacji”)
    foreign = next(
        q.field
        for t in res.form.tabs
        for q in iter_questions(t.questions)
        if q.field.tech_name == "kod_pocztowy_zagranica"
    )
    assert "ZIP_CODE" not in foreign.validation


def _dup_tech(d: dict[str, Any]) -> None:
    _sec(d)[0]["field"]["techName"] = "imie"  # nazwa_organu -> imie (już istnieje w „Twoje dane”)


def _no_finish(d: dict[str, Any]) -> None:
    d["tabs"].pop()
    d["flow"]["links"].pop()


def _bad_jsonata(d: dict[str, Any]) -> None:
    state = _sec(d, 0, 1)[0]["field"]["states"][0]
    state["query"] = state["query"].rstrip(")")  # niedomknięty nawias


def _garbage_jsonata(d: dict[str, Any]) -> None:
    _sec(d, 0, 1)[0]["field"]["states"][0]["query"] = "and and ("


def _overlap(d: dict[str, Any]) -> None:
    grid = _sec(d, 0, 3)  # adres_zamieszkania
    grid[1]["y"] = grid[0]["y"]
    grid[2]["x"], grid[2]["cols"] = 2, 3  # poza siatką


def _bad_slug(d: dict[str, Any]) -> None:
    _sec(d)[0]["field"]["techName"] = "Nazwa organu ąę"


def _loose_field(d: dict[str, Any]) -> None:
    sec = d["tabs"][1]["questions"][0]
    d["tabs"][1]["questions"] = sec["field"]["repeatingSectionGrid"]


def _finish_input(d: dict[str, Any]) -> None:
    _sec(d, 3, 0)[0]["field"]["type"] = "TEXT_FIELD"


def _broken_flow(d: dict[str, Any]) -> None:
    d["flow"]["links"] = d["flow"]["links"][:1]


def _dangling_ref(d: dict[str, Any]) -> None:
    st = _sec(d, 0, 1)[0]["field"]["states"][0]
    st["query"] = st["query"].replace("'wybierz_w_czyim_imieniu_wnioskujesz'", "'nie_ma_takiego_pola'")


def _hide_state(d: dict[str, Any]) -> None:
    _sec(d, 0, 1)[0]["field"]["states"][0]["type"] = "HIDE"


def _dup_uuid(d: dict[str, Any]) -> None:
    _sec(d)[0]["field"]["id"] = d["tabs"][0]["questions"][1]["field"]["id"]


def _nested_section(d: dict[str, Any]) -> None:
    inner = d["tabs"][0]["questions"].pop(1)
    inner["y"] = 1
    _sec(d, 0, 0).append(inner)


CASES = [
    ("COI-R11", _dup_tech),
    ("COI-R04", _no_finish),
    ("COI-R18", _bad_jsonata),
    ("COI-R18", _garbage_jsonata),
    ("COI-R14", _overlap),
    ("COI-R13", _overlap),
    ("COI-R12", _bad_slug),
    ("COI-R06", _loose_field),
    ("COI-R08", _finish_input),
    ("COI-R09", _broken_flow),
    ("COI-R19", _dangling_ref),
    ("COI-R20", _hide_state),
    ("COI-R10", _dup_uuid),
    ("COI-R07", _nested_section),
]


@pytest.mark.parametrize(("rule_id", "mutate"), CASES, ids=[f"{r}-{m.__name__}" for r, m in CASES])
def test_broken_fails_then_repairs(raw: dict[str, Any], rule_id: str, mutate: Callable[[dict[str, Any]], None]) -> None:
    form = _form(raw, mutate)
    before = _failed(form, repair=False)
    assert before.get(rule_id) == "error", before

    res = validate(form, repair=True)
    errors = {r.id for r in res.rules if not r.passed and r.severity == "error"}
    assert errors == set(), [r.message for r in res.rules if r.id in errors]
    assert any(r.rule_id == rule_id for r in res.repairs)
    rr = next(r for r in res.rules if r.id == rule_id)
    assert rr.passed and rr.repaired
    # naprawiony formularz jest poprawny także przy ponownej walidacji (idempotencja)
    again = validate(res.form, repair=True)
    assert again.repairs == []
    for rep in res.repairs:
        assert rep.path.startswith("/") and rep.description


def test_missing_finish_adds_tab_and_flow(raw: dict[str, Any]) -> None:
    res = validate(_form(raw, _no_finish))
    assert res.form.tabs[-1].type == "FINISH"
    links = [(link.source, link.target) for link in res.form.flow.links]
    assert links[-1] == (res.form.tabs[-2].id, res.form.tabs[-1].id)


def test_rename_updates_jsonata(raw: dict[str, Any]) -> None:
    def mutate(d: dict[str, Any]) -> None:
        grid = _sec(d, 0, 1)
        old = grid[1]["field"]["techName"]
        new = "Wybierz w czyim imieniu"
        grid[1]["field"]["techName"] = new
        st = grid[0]["field"]["states"][0]
        st["query"] = st["query"].replace(f"'{old}'", f"'{new}'")

    res = validate(_form(raw, mutate))
    assert not [r for r in res.rules if not r.passed and r.severity == "error"]
    q = res.form.tabs[0].questions[1].field.repeating_section_grid[0].field.states[0].query
    assert "'wybierz_w_czyim_imieniu' in field.techName" in q


def test_overlap_relayout_single_column(raw: dict[str, Any]) -> None:
    res = validate(_form(raw, _overlap))
    grid = res.form.tabs[0].questions[3].field.repeating_section_grid
    assert all(q.x == 0 and q.cols == 3 for q in grid)
    assert len({q.y for q in grid}) == len(grid)


def test_bad_jsonata_balanced_not_dropped(raw: dict[str, Any]) -> None:
    res = validate(_form(raw, _bad_jsonata))
    field = res.form.tabs[0].questions[1].field.repeating_section_grid[0].field
    assert len(field.states) == 1


def test_select_without_options_not_repairable(raw: dict[str, Any]) -> None:
    def mutate(d: dict[str, Any]) -> None:
        _sec(d, 0, 1)[1]["field"]["options"] = []

    res = validate(_form(raw, mutate))
    r15 = next(r for r in res.rules if r.id == "COI-R15")
    assert not r15.passed and r15.targets


def test_long_title_truncated(raw: dict[str, Any]) -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["title"] = "Wniosek " + "bardzo " * 50

    assert _failed(_form(raw, mutate), repair=False)["COI-R02"] == "error"
    res = validate(_form(raw, mutate))
    assert len(res.form.title) <= 255
