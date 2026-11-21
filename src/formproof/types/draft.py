"""DraftForm – pośrednia reprezentacja (INFER/LLM/DICT -> BUILD). Bez UUID i siatki; z pewnością i źródłem decyzji."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from .form import ConsentSectionConfig, FieldState, FieldType, Validator

DecidedBy = Literal["rules", "llm", "dict", "repair"]


class Evidence(BaseModel):
    block_ids: list[str] = []  # id bloków SourceDoc
    by: DecidedBy
    reason: str | None = None  # po polsku, np. "etykieta zawiera 'PESEL'"


class DraftOption(BaseModel):
    name: str
    checked: bool | None = None


class ShowWhen(BaseModel):
    """Pokaż pole, gdy pole `when_key` ma wartość `equals` (BUILD -> JSONata)."""

    when_key: str
    equals: str
    negate: bool = False


class DraftField(BaseModel):
    key: str  # tymczasowy klucz (np. "f12"); BUILD nadaje UUID i techName
    type: FieldType
    title: str
    description: str | None = None
    tooltip_message: str | None = None
    options: list[DraftOption] = []
    validation: list[Validator] = []
    read_only: bool = False
    dictionary_name: str | None = None
    multi_level_tree: bool | None = None
    default_value: str | list[str] | None = None
    default_value_type: Literal["EXTERNAL_SYSTEM"] | None = None
    consent_section_config: ConsentSectionConfig | None = None
    children: list[DraftField] = []  # dla SECTION / REPEATING_SECTION
    show_when: list[ShowWhen] = []
    states: list[FieldState] = []  # gotowe stany, BUILD przepisuje 1:1
    width: Literal[1, 2, 3] | None = None  # sugerowana szerokość w kolumnach
    confidence: float  # 0..1
    evidence: list[Evidence] = []


class DraftTab(BaseModel):
    title: str
    type: Literal["MAIN", "FINISH"] = "MAIN"
    fields: list[DraftField] = []
    confidence: float = 1.0
    evidence: list[Evidence] = []


class DraftForm(BaseModel):
    title: str
    title_confidence: float = 0.5
    title_evidence: list[Evidence] = []
    tabs: list[DraftTab] = []


def iter_draft(fields: list[DraftField]):  # type: ignore[no-untyped-def]
    for f in fields:
        yield f
        yield from iter_draft(f.children)


DraftField.model_rebuild()
