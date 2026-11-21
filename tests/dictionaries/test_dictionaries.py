from __future__ import annotations

from pathlib import Path

from formproof.dictionaries import apply_dictionaries, get_dictionary, list_dictionaries
from formproof.infer import infer
from formproof.types.draft import DraftField, DraftForm, DraftOption, DraftTab, iter_draft
from formproof.types.source import SourceDoc

FIX = Path(__file__).parent.parent / "fixtures"


def _f(key: str, title: str, type_: str = "TEXT_FIELD", opts: list[str] | None = None) -> DraftField:
    return DraftField(
        key=key, type=type_, title=title, options=[DraftOption(name=o) for o in opts or []], confidence=0.8
    )  # type: ignore[arg-type]


def _form(*sections: tuple[str, list[DraftField]]) -> DraftForm:
    return DraftForm(
        title="T",
        tabs=[
            DraftTab(
                title="Dane",
                fields=[
                    DraftField(key=f"s{i}", type="SECTION", title=t, children=ch, confidence=1)
                    for i, (t, ch) in enumerate(sections)
                ],
            )
        ],
    )


def _by_key(d: DraftForm) -> dict[str, DraftField]:
    return {f.key: f for t in d.tabs for f in iter_draft(t.fields)}


def test_list_and_get() -> None:
    ds = {d["name"]: d for d in list_dictionaries()}
    assert {"Kraje", "Województwo", "Numery kierunkowe", "Powiat", "Gmina", "Miejscowość"} <= set(ds)
    assert ds["Powiat"]["sample"] is True and ds["Kraje"]["sample"] is False
    assert len(get_dictionary("Województwo") or []) == 16
    assert "Polska" in (get_dictionary("Kraje") or [])
    assert any(i.startswith("+48") for i in get_dictionary("Numery kierunkowe") or [])
    assert get_dictionary("brak") is None


def test_label_matching_and_no_mutation() -> None:
    draft = _form(("Adres", [_f("a", "Kraj"), _f("b", "Obywatelstwo"), _f("c", "Województwo"), _f("d", "Ulica")]))
    before = draft.model_dump()
    res = apply_dictionaries(draft)
    assert draft.model_dump() == before
    m = _by_key(res.draft)
    assert m["a"].dictionary_name == "Kraje" and m["a"].type == "SELECT"
    assert m["b"].dictionary_name == "Kraje"
    assert m["c"].dictionary_name == "Województwo"
    assert m["d"].dictionary_name is None and m["d"].type == "TEXT_FIELD"
    assert any(e.by == "dict" for e in m["a"].evidence)


def test_options_overlap_clears_options() -> None:
    woj = get_dictionary("Województwo") or []
    draft = _form(("X", [_f("a", "Wybierz region", "RADIO", woj[:8] + ["mazowieckie"])]))
    m = _by_key(apply_dictionaries(draft).draft)
    assert m["a"].dictionary_name == "Województwo" and m["a"].type == "SELECT" and m["a"].options == []


def test_powiat_text_field_untouched_but_select_assigned() -> None:
    draft = _form(("X", [_f("a", "Powiat"), _f("b", "Powiat", "SELECT", ["x", "y"])]))
    m = _by_key(apply_dictionaries(draft).draft)
    assert m["a"].dictionary_name is None
    assert m["b"].dictionary_name == "Powiat"


def test_initial_data_only_applicant() -> None:
    draft = _form(
        ("Twoje dane", [_f("n", "Imię"), _f("s", "Nazwisko"), _f("p", "PESEL")]),
        ("Dane do kontaktu", [_f("t", "Numer telefonu"), _f("e", "Adres e-mail")]),
        ("Dane pełnomocnika", [_f("n2", "Imię"), _f("s2", "Nazwisko")]),
        ("Dane innej osoby", [_f("n3", "Imię")]),
    )
    m = _by_key(apply_dictionaries(draft).draft)
    assert m["n"].default_value == "MLPZ.name" and m["n"].read_only and m["n"].default_value_type == "EXTERNAL_SYSTEM"
    assert m["s"].default_value == "MLPZ.surname"
    assert m["p"].default_value == "MLPZ.pesel"
    assert m["t"].default_value == "MLPZ.phoneNumber" and not m["t"].read_only
    assert m["e"].default_value == "MLPZ.email"
    for k in ("n2", "s2", "n3"):
        assert m[k].default_value is None


def test_proposals() -> None:
    opts = [f"opcja {i}" for i in range(10)]
    draft = _form(
        (
            "X",
            [
                _f("a", "Urząd skarbowy"),
                _f("b", "Rodzaj dokumentu", "SELECT", opts),
                _f("c", "Wybór", "RADIO", ["a", "b", "c"]),
                _f("d", "Wybór 2", "RADIO", ["c", "b", "a"]),
            ],
        )
    )
    res = apply_dictionaries(draft)
    names = {p.name: p for p in res.proposed}
    assert "Urzędy skarbowe" in names and "Rodzaje dokumentów" in names
    assert names["Rodzaje dokumentów"].items == opts
    assert "Wybór" in names


def test_idempotent() -> None:
    draft = _form(("Twoje dane", [_f("k", "Kraj"), _f("n", "Imię")]))
    once = apply_dictionaries(draft).draft
    twice = apply_dictionaries(once).draft
    assert once.model_dump() == twice.model_dump()


def test_pipeline_form1() -> None:
    doc = SourceDoc.model_validate_json((FIX / "sample-source1.json").read_text(encoding="utf-8"))
    res = apply_dictionaries(infer(doc))
    fields = [f for t in res.draft.tabs for f in iter_draft(t.fields)]
    assert any(f.dictionary_name == "Kraje" for f in fields)
    defaults = {f.default_value for f in fields if isinstance(f.default_value, str)}
    assert {"MLPZ.name", "MLPZ.surname", "MLPZ.street", "MLPZ.building", "MLPZ.phoneNumber", "MLPZ.email"} <= defaults
