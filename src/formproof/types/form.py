"""FormDefinition – JSON importowany do kreatora eUsług COI.

Źródło: materiały COI (importowanyPlikJsonSchemat.json, OpisImportowanegoPlikuJSON, example1).
Uwaga: schema ma literówkę `repetingSectionGrid`; przykłady COI używają `repeatingSectionGrid` – emitujemy tę drugą.
Serializacja: `form.dump()` (bez None, aliasy camelCase).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

FieldType = Literal[
    "SECTION",
    "REPEATING_SECTION",
    "TEXT_FIELD",
    "TEXTAREA",
    "NUMBER",
    "DATEPICKER",
    "SELECT",
    "RADIO",
    "CHECKBOX",
    "FILE_UPLOADER",
    "CONSENT_SECTION",
    "TEXT_BLOCK",
    "INFO_SECTION",
]
FIELD_TYPES: tuple[str, ...] = FieldType.__args__  # type: ignore[attr-defined]
CONTAINER_TYPES: frozenset[str] = frozenset({"SECTION", "REPEATING_SECTION"})
PRESENTATIONAL_TYPES: frozenset[str] = frozenset({"TEXT_BLOCK", "INFO_SECTION"})

Validator = Literal["REQUIRED", "EMAIL", "PESEL", "NIP", "REGON", "ZIP_CODE", "EPUAP", "ADE", "SERIAL_NUMBER_ID_CARD"]
VALIDATORS: tuple[str, ...] = Validator.__args__  # type: ignore[attr-defined]

TabType = Literal["MAIN", "FINISH"]

# Szerokość siatki w kreatorze COI (przykłady: x+cols <= 3).
GRID_COLS = 3


class _Model(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    def dump(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True, exclude_none=True, mode="json")


class FieldOption(_Model):
    id: str
    name: str
    tech_name: str = Field(alias="techName")


class FieldState(_Model):
    type: str  # SHOW | HIDE | ...
    query: str  # wyrażenie JSONata


class Consent(_Model):
    description: str


class ConsentSectionConfig(_Model):
    consents: list[Consent] = []
    required: bool = False
    files: list[Any] = []


class FormField(_Model):
    id: str
    type: FieldType
    tech_name: str = Field(alias="techName")
    title: str
    description: str = ""
    options: list[FieldOption] = []
    validation: list[Validator] = []
    read_only: bool = Field(default=False, alias="readOnly")
    repeating_section_grid: list[Question] = Field(default_factory=list, alias="repeatingSectionGrid")
    states: list[FieldState] = []
    question_order: int = Field(default=0, alias="questionOrder")
    tooltip_message: str = Field(default="", alias="tooltipMessage")
    dictionary_name: str | None = Field(default=None, alias="dictionaryName")
    multi_level_tree: bool | None = Field(default=None, alias="multiLevelTree")
    search_enabled: bool | None = Field(default=None, alias="searchEnabled")
    # string lub tablica (SELECT z domyślną wartością, np. ["Polska"])
    default_value: str | list[str] | None = Field(default=None, alias="defaultValue")
    default_value_type: Literal["EXTERNAL_SYSTEM", ""] | None = Field(default=None, alias="defaultValueType")
    consent_section_config: ConsentSectionConfig | None = Field(default=None, alias="consentSectionConfig")

    @field_validator("validation", "options", "states", "repeating_section_grid", mode="before")
    @classmethod
    def _empty_obj_as_list(cls, v: Any) -> Any:
        # materiały COI zawierają czasem `{}` zamiast `[]`
        return [] if v is None or v == {} else v


class Question(_Model):
    """Pozycja w siatce: CSS grid-area: {y+1} / {x+1} / span {rows} / span {cols}."""

    x: int
    y: int
    rows: int = 1
    cols: int = 1
    field: FormField


class Tab(_Model):
    id: str
    title: str
    type: TabType
    questions: list[Question] = []


class FlowLink(_Model):
    id: str
    source: str
    target: str


class Flow(_Model):
    links: list[FlowLink] = []


class FormDefinition(_Model):
    title: str
    tabs: list[Tab]
    flow: Flow = Flow()


def iter_questions(questions: list[Question]):  # type: ignore[no-untyped-def]
    """Wszystkie pytania rekurencyjnie (w głąb sekcji)."""
    for q in questions:
        yield q
        yield from iter_questions(q.field.repeating_section_grid)


FormField.model_rebuild()
