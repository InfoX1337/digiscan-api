"""STUB – runda 2 (LLM). Nigdy nie rzuca."""

from __future__ import annotations

from ..types.draft import DraftForm
from ..types.source import SourceDoc
from ..types.stages import LlmResult


def enrich(doc: SourceDoc, draft: DraftForm) -> LlmResult:
    return LlmResult(draft=draft, used=False)
