"""SourceDoc – znormalizowany wynik ekstrakcji z dowolnego formatu.

Kontrakt: EXTRACT (out) -> INFER (in). Kolejność `blocks` = kolejność czytania.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

SourceFormat = Literal["pdf", "image", "docx", "doc", "xlsx", "ods"]

# text: akapit/linia; cell: komórka tabeli; checkbox: pole wyboru (etykieta w text); line: miejsce do wpisania
BlockKind = Literal["text", "cell", "checkbox", "line"]


class BBox(BaseModel):
    """Jednostki strony (PDF: pt, obraz: px), początek w lewym górnym rogu."""

    x: float
    y: float
    w: float
    h: float


class BlockStyle(BaseModel):
    bold: bool | None = None
    italic: bool | None = None
    font_size: float | None = None  # pt (PDF/DOCX) lub wysokość px (OCR)
    heading: int | None = None  # Heading1 -> 1
    centered: bool | None = None


class SourceBlock(BaseModel):
    id: str  # stabilne w dokumencie, np. "p1-b12"
    page: int  # strona / arkusz, od 1
    kind: BlockKind
    text: str
    bbox: BBox | None = None
    style: BlockStyle | None = None
    # dla `cell`: tabela, wiersz, kolumna (od 0), rozpiętości
    table: int | None = None
    row: int | None = None
    col: int | None = None
    row_span: int | None = None
    col_span: int | None = None
    checked: bool | None = None  # dla `checkbox`
    confidence: float = 1.0  # OCR: conf/100; tekst natywny: 1


class SourcePage(BaseModel):
    page: int
    width: float | None = None
    height: float | None = None
    name: str | None = None  # arkusz XLSX/ODS


class SourceDoc(BaseModel):
    filename: str
    format: SourceFormat
    ocr: bool = False
    pages: list[SourcePage] = []
    blocks: list[SourceBlock] = []
    warnings: list[str] = []
