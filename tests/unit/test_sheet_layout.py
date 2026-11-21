"""Arkusze jako strona (siatka, obramowania = miejsca do wpisania) + INFER: podpis "/ … /", wyliczenie."""

from __future__ import annotations

import io

import openpyxl
from openpyxl.styles import Border, Side

from formproof.extract import extract
from formproof.infer import infer
from formproof.types.draft import DraftField
from formproof.types.source import SourceBlock, SourceDoc, SourcePage
from formproof.types.stages import ExtractInput


def _flat(fields: list[DraftField]) -> list[DraftField]:
    out: list[DraftField] = []
    for f in fields:
        out.append(f)
        out.extend(_flat(f.children))
    return out


def _all(doc: SourceDoc) -> list[DraftField]:
    return [f for t in infer(doc).tabs for f in _flat(t.fields)]


def _xlsx() -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    assert ws is not None
    for c in range(1, 30):
        ws.column_dimensions[openpyxl.utils.get_column_letter(c)].width = 1.2
    dotted = Border(bottom=Side(style="dotted"))
    for c in range(1, 20):  # pusta komórka z dolnym obramowaniem = linia do wpisania
        ws.cell(row=3, column=c).border = dotted
    ws.cell(row=4, column=1, value="(imię i nazwisko)")
    ws.cell(row=6, column=1, value="w miejscowości")
    for c in range(10, 28):
        ws.cell(row=6, column=c).border = dotted
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_xlsx_borders_become_lines_with_bbox() -> None:
    doc = extract(ExtractInput("a.xlsx", "xlsx", _xlsx()))
    kinds = [b.kind for b in doc.blocks]
    assert kinds[:2] == ["line", "text"]  # linia nad podpisem
    assert all(b.bbox is not None for b in doc.blocks)
    titles = {f.title for f in _all(doc)}
    assert {"Imię", "Nazwisko", "Miejscowość"} <= titles


def _doc(*items: tuple[str, str]) -> SourceDoc:
    blocks = [SourceBlock(id=f"p1-b{i}", page=1, kind=k, text=t) for i, (k, t) in enumerate(items, 1)]  # type: ignore[arg-type]
    return SourceDoc(filename="x.docx", format="docx", pages=[SourcePage(page=1)], blocks=blocks)


def test_slash_hint_and_enumeration_choice() -> None:
    doc = _doc(
        ("line", ""),
        ("text", "/ PESEL /"),
        ("text", "Proszę o wydanie dokumentu o:*"),
        ("text", "posiadaniu gruntu"),
        ("text", "dzierżawie gruntu"),
        ("text", "inne"),
        ("line", ""),
    )
    fields = _all(doc)
    assert any("PESEL" in f.validation for f in fields)
    radio = next(f for f in fields if f.type == "RADIO")
    assert [o.name for o in radio.options] == ["Posiadaniu gruntu", "Dzierżawie gruntu", "Inne"]
    other = next(f for f in fields if f.type == "TEXT_FIELD" and f.title == "Inne")
    assert other.show_when and other.show_when[0].when_key == radio.key
