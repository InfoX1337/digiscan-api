"""LLM (R3): przebudowa struktury – parsowanie odpowiedzi i ugruntowanie w dokumencie."""

from __future__ import annotations

from formproof.llm import structure
from formproof.types.draft import DraftField, DraftForm, DraftTab, iter_draft
from formproof.types.source import BBox, SourceBlock, SourceDoc

TEXTS = [
    "WNIOSEK O WYDANIE ZEZWOLENIA NA UTRZYMYWANIE ZWIERZĄT",
    "B | INFORMACJA O POSIADANYM ZWIERZĘCIU (w przypadku kilku pobrać załącznik)",
    "Rasa: ……",
    "Data urodzenia zwierzęcia: ……",
    "Płeć:",
    "samiec",
    "samica",
    "Opłata skarbowa – 82 zł. Numer konta: 12 1223 1232 1233 2312 2342 2342",
    "1. Oświadczam, że zwierzę nie będzie wykorzystywane do polowań.",
]


def _doc() -> SourceDoc:
    blocks = [
        SourceBlock(
            id=f"p1-b{i}",
            page=1,
            kind="checkbox" if t in ("samiec", "samica") else "text",
            text=t,
            bbox=BBox(x=0, y=20 * i, w=300, h=12),
        )
        for i, t in enumerate(TEXTS)
    ]
    return SourceDoc(filename="x.pdf", format="pdf", blocks=blocks)


def _draft() -> DraftForm:
    return DraftForm(
        title="Wniosek o wydanie zezwolenia",
        title_confidence=0.9,
        tabs=[
            DraftTab(
                title="Dane",
                fields=[
                    DraftField(
                        key="f1",
                        type="SECTION",
                        title="Twoje dane",
                        confidence=0.9,
                        children=[
                            DraftField(key="f2", type="TEXT_FIELD", title="Imię", confidence=0.9),
                            DraftField(key="f3", type="TEXT_FIELD", title="Nazwisko", confidence=0.9),
                        ],
                    )
                ],
            ),
            DraftTab(
                title="Szczegóły wniosku",
                fields=[
                    DraftField(
                        key="f4",
                        type="SECTION",
                        title="Kod pocztowy",
                        confidence=0.5,
                        children=[
                            DraftField(key="f5", type="TEXT_FIELD", title="Rasa psaz BB zir", confidence=0.17),
                        ],
                    )
                ],
            ),
        ],
    )


RESP = {
    "title": "Wniosek o wydanie zezwolenia na utrzymywanie zwierząt",
    "lines": [
        "S|Dane wnioskodawcy",
        "F|TEXT_FIELD|Imię i nazwisko|W",
        "S|Informacja o posiadanymzwierzęciu",
        "F|TEXT_FIELD|Rasa|W",
        "F|DATE|Data urodzenia zwierzęcia|W",
        "F|RADIO|Płeć|samiec;samica;inna|W",
        "F|TEXT_FIELD|Kolor sierści|O",
        "F|TEXT_FIELD|Numer konta|O",
        "Z|Oświadczam, że zwierzę nie będzie wykorzystywane do polowań.",
    ],
}


def _fields(d: DraftForm, tab: str) -> list[DraftField]:
    t = next(x for x in d.tabs if x.title == tab)
    return list(iter_draft(t.fields))


def test_parse_lines_and_aliases() -> None:
    title, sections, consents = structure.parse(RESP)
    assert title.startswith("Wniosek")
    assert [s for s, _ in sections] == ["Dane wnioskodawcy", "Informacja o posiadanymzwierzęciu"]
    assert sections[1][1][1].type == "DATEPICKER"
    assert sections[1][1][2].options == ["Samiec", "Samica", "Inna"]
    assert consents == ["Oświadczam, że zwierzę nie będzie wykorzystywane do polowań."]


def test_parse_merges_address_parts() -> None:
    _, sections, _ = structure.parse(
        {"lines": ["S|Dane", "F|TEXT_FIELD|Ulica|W", "F|TEXT_FIELD|Kod pocztowy|W", "F|TEXT_FIELD|Telefon|W"]}
    )
    assert [(f.type, f.label) for f in sections[0][1]] == [("ADRES", "Adres"), ("TEXT_FIELD", "Telefon")]


def test_apply_grounds_every_field() -> None:
    res = structure.apply(_doc(), _draft(), RESP)
    assert res.applied
    det = _fields(res.draft, "Szczegóły wniosku")
    titles = [f.title for f in det]
    # nagłówek w brzmieniu z dokumentu (literówka LLM poprawiona), litera sekcji z tabeli usunięta
    assert titles[0] == "Informacja o posiadanym zwierzęciu"
    assert "Rasa" in titles and "Data urodzenia zwierzęcia" in titles
    assert "Kolor sierści" not in titles  # brak w dokumencie – odrzucone
    assert "Numer konta" not in titles  # nadrukowana wartość, nie pole
    assert "Rasa psaz BB zir" not in titles  # szum OCR z reguł zastąpiony
    plec = next(f for f in det if f.title == "Płeć")
    assert plec.type == "RADIO" and [o.name for o in plec.options] == ["Samiec", "Samica"]  # 'inna' nieugruntowana
    for f in det:
        assert any(e.block_ids for e in f.evidence), f.title
    # 'Imię i nazwisko' już jest w zakładce Dane
    assert all(f.title != "Imię i nazwisko" for t in res.draft.tabs for f in iter_draft(t.fields))
    consents = [f for t in res.draft.tabs for f in iter_draft(t.fields) if f.type == "CONSENT_SECTION"]
    assert consents and consents[0].consent_section_config is not None
    assert "polowań" in consents[0].consent_section_config.consents[0].description
    assert res.draft.title == "Wniosek o wydanie zezwolenia na utrzymywanie zwierząt"  # dokończony tytuł


def test_apply_rejects_weak_answer() -> None:
    src = _draft()
    res = structure.apply(_doc(), src, {"title": "", "lines": ["S|Coś", "F|TEXT_FIELD|Zupełnie zmyślone pole|W"]})
    assert not res.applied and res.draft is src


def test_prompt_skips_rodo_and_joins_rows() -> None:
    blocks = [
        SourceBlock(id="b1", page=1, kind="text", text="Płeć:", bbox=BBox(x=0, y=0, w=50, h=10)),
        SourceBlock(id="b2", page=1, kind="checkbox", text="pies", bbox=BBox(x=100, y=1, w=50, h=10)),
        SourceBlock(id="b3", page=1, kind="text", text="Rasa", bbox=BBox(x=0, y=30, w=50, h=10)),
        SourceBlock(
            id="b4",
            page=1,
            kind="text",
            text="INFORMACJE DOTYCZĄCE PRZETWARZANIA TWOICH DANYCH",
            bbox=BBox(x=0, y=60, w=50, h=10),
        ),
        SourceBlock(id="b5", page=1, kind="text", text="Administrator danych …", bbox=BBox(x=0, y=90, w=50, h=10)),
    ]
    txt = structure.doc_lines(SourceDoc(filename="x.pdf", format="pdf", blocks=blocks))
    assert "Płeć: | ☐ pies" in txt
    assert "Administrator" not in txt and "RODO" in txt
