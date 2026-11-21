"""Report – dowód i zaufanie (wyróżnik FormProof). Zwracany obok czystego `form`. Klucze JSON w camelCase."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from .source import BBox, SourceFormat

ApiErrorCode = Literal[
    "FILE_TOO_LARGE",
    "BAD_EXTENSION",
    "MIME_MISMATCH",
    "BAD_FILENAME",
    "EMPTY",
    "NO_FILE",
    "TOO_MANY_FILES",
    "UNAUTHORIZED",
    "NOTHING_EXTRACTED",
    "TIMEOUT",
    "INVALID_FORM",
    "NOT_FOUND",
    "INTERNAL",
]


class _Camel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, serialize_by_alias=True)


class SourceRef(_Camel):
    page: int
    bbox: BBox | None = None
    text: str
    block_ids: list[str] = []


class FieldReport(_Camel):
    id: str  # UUID pola w `form`
    tech_name: str
    title: str
    type: str
    confidence: float
    sources: list[SourceRef] = []  # puste dla pól dodanych przez auto-naprawę
    decided_by: list[Literal["rules", "llm", "dict", "repair"]] = []
    reasons: list[str] = []


class RuleResult(_Camel):
    id: str  # stabilny, np. "COI-TAB-FINISH"
    title: str  # po polsku, z materiałów COI
    severity: Literal["error", "warning", "info"]
    passed: bool
    repaired: bool = False
    targets: list[str] = []  # UUID/techName pól
    message: str | None = None


class Repair(_Camel):
    rule_id: str
    path: str  # JSON Pointer w `form`
    description: str
    before: Any = None
    after: Any = None


class ReviewItem(_Camel):
    field_id: str
    tech_name: str
    title: str
    confidence: float
    reason: str


class ProposedDictionary(_Camel):
    name: str
    field_id: str
    items: list[str]
    reason: str


class PagePreview(_Camel):
    """Podgląd strony oryginału dla UI (bbox w tych samych jednostkach co width/height)."""

    page: int
    width: float
    height: float
    png_base64: str


class LlmInfo(_Camel):
    used: bool = False
    model: str | None = None
    error: str | None = None


class Report(_Camel):
    filename: str
    format: SourceFormat
    ocr: bool
    confidence: float  # średnia ważona 0..1
    fields: dict[str, FieldReport] = {}
    review: list[ReviewItem] = []
    rules: list[RuleResult] = []
    repairs: list[Repair] = []
    proposed_dictionaries: list[ProposedDictionary] = []
    warnings: list[str] = []
    timings: dict[str, int] = {}
    llm: LlmInfo = LlmInfo()
    previews: list[PagePreview] | None = None


class ApiError(_Camel):
    code: ApiErrorCode
    message: str
