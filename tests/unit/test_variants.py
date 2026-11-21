"""Kilka wniosków w jednym pliku: spis wariantów -> wybór 'Rodzaj wniosku' + sekcje warunkowe (SHOW)."""

from __future__ import annotations

from formproof.build import build
from formproof.infer import infer
from formproof.infer.variants import CHOICE_TITLE, _common_title
from formproof.types.source import SourceBlock, SourceDoc, SourcePage
from formproof.validate import validate

TITLES = ["Wniosek o przyznanie stypendium Rady Gminy", "Wniosek o przyznanie nagrody Rady Gminy"]


def _part(numeral: str, title: str, extra: str) -> list[str]:
    return [
        f"{numeral}{title}",
        "1. Dane wnioskodawcy",
        "Imię ……………………",
        "Nazwisko ……………………",
        "Numer telefonu ……………………",
        "2. Dane kandydata",
        "Imię ……………………",
        "Nazwisko ……………………",
        "Data urodzenia ……………………",
        f"3. {extra}",
        f"{extra} ……………………",
        "Uzasadnienie ……………………",
        "Data sporządzenia wniosku ……………",
    ]


def _doc(numerals: list[str]) -> SourceDoc:
    texts = ["Rodzaje wniosków:", *(f"{n}{t}" for n, t in zip(numerals, TITLES, strict=True))]
    texts += _part(numerals[0], TITLES[0], "Osiągnięcia sportowe")
    texts += _part(numerals[1], TITLES[1], "Wyniki w zawodach")
    blocks = [SourceBlock(id=f"p1-b{i}", page=1, kind="text", text=t) for i, t in enumerate(texts, 1)]
    return SourceDoc(filename="x.docx", format="docx", pages=[SourcePage(page=1)], blocks=blocks)


def _check(doc: SourceDoc) -> None:
    d = infer(doc)
    assert d.title == "Wniosek o przyznanie stypendium lub nagrody Rady Gminy"
    first = d.tabs[0].fields[0]
    choice = first.children[0]
    assert choice.title == CHOICE_TITLE and [o.name for o in choice.options] == TITLES
    tops = [f for t in d.tabs for f in t.fields]
    conditional = [f for f in tops if any(w.when_key == choice.key for w in f.show_when)]
    assert conditional, "brak sekcji warunkowych wariantów"
    assert {w.equals for f in conditional for w in f.show_when if w.when_key == choice.key} == set(TITLES)
    keys = [f.key for t in d.tabs for f in t.fields] + [c.key for t in d.tabs for f in t.fields for c in f.children]
    assert len(keys) == len(set(keys)), "klucze pól muszą być unikalne między wariantami"
    form = validate(build(d).form, repair=True)
    assert not [r.id for r in form.rules if r.severity == "error" and not r.passed]


def test_roman_numerals() -> None:
    _check(_doc(["I. ", "II. "]))


def test_list_without_numbers() -> None:
    _check(_doc(["", ""]))


def test_plain_form_not_split() -> None:
    blocks = [
        SourceBlock(id=f"b{i}", page=1, kind="text", text=t)
        for i, t in enumerate(
            ["Wniosek o wydanie zaświadczenia", "I. Dane wnioskodawcy", "Imię ……", "II. Dane", "Nazwisko ……"]
        )
    ]
    d = infer(SourceDoc(filename="x.docx", format="docx", pages=[SourcePage(page=1)], blocks=blocks))
    assert all(c.title != CHOICE_TITLE for t in d.tabs for f in t.fields for c in f.children)


def test_common_title_ocr_typo() -> None:
    assert _common_title(["Whiosek o przyznanie stypendium", "Wniosek o przyznanie nagrody"]).endswith(
        "stypendium lub nagrody"
    )
