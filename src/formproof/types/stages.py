"""Sygnatury kroków pipeline'u – kontrakt między strumieniami.

Każdy strumień eksportuje dokładnie tę funkcję ze swojego `__init__.py`:
- formproof.extract.extract: ExtractFn
- formproof.infer.infer: InferFn
- formproof.llm.enrich: EnrichFn (nigdy nie rzuca; fallback = draft bez zmian)
- formproof.dictionaries.apply_dictionaries: DictFn
- formproof.build.build: BuildFn
- formproof.validate.validate: ValidateFn (nie mutuje wejścia)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from .draft import DraftForm
from .form import FormDefinition
from .report import Repair, RuleResult
from .source import SourceDoc, SourceFormat


@dataclass
class ExtractInput:
    filename: str
    format: SourceFormat
    data: bytes
    max_ocr_pages: int = 5
    deadline: float | None = None  # time.monotonic() deadline


class ExtractFn(Protocol):
    def __call__(self, inp: ExtractInput) -> SourceDoc: ...


class InferFn(Protocol):
    def __call__(self, doc: SourceDoc) -> DraftForm: ...


@dataclass
class LlmResult:
    draft: DraftForm
    used: bool
    model: str | None = None
    error: str | None = None


class EnrichFn(Protocol):
    def __call__(self, doc: SourceDoc, draft: DraftForm) -> LlmResult: ...


@dataclass
class ProposedDict:
    name: str
    field_key: str  # klucz DraftField
    items: list[str]
    reason: str


@dataclass
class DictResult:
    draft: DraftForm
    proposed: list[ProposedDict] = field(default_factory=list)


class DictFn(Protocol):
    def __call__(self, draft: DraftForm) -> DictResult: ...


@dataclass
class BuildResult:
    form: FormDefinition
    key_to_id: dict[str, str]  # DraftField.key -> UUID pola w form


class BuildFn(Protocol):
    def __call__(self, draft: DraftForm) -> BuildResult: ...


@dataclass
class ValidateResult:
    form: FormDefinition  # po auto-naprawie (kopia)
    rules: list[RuleResult]
    repairs: list[Repair]


class ValidateFn(Protocol):
    def __call__(self, form: FormDefinition, repair: bool = True) -> ValidateResult: ...
