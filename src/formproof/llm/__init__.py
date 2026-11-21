"""LLM (R1): opcjonalne wzbogacenie DraftForm przez lokalny model Ollama. Nigdy nie rzuca."""

from __future__ import annotations

import logging
import time
from typing import Any

from ..config import get_settings
from ..types.draft import DraftForm
from ..types.source import SourceDoc
from ..types.stages import LlmResult
from . import client
from .fusion import fuse
from .prompt import build_batches

log = logging.getLogger(__name__)

__all__ = ["enrich"]


def enrich(doc: SourceDoc, draft: DraftForm) -> LlmResult:
    try:
        return _enrich(doc, draft)
    except Exception as e:  # noqa: BLE001 – kontrakt: nigdy nie rzuca
        log.warning("LLM enrich failed: %s", e)
        return LlmResult(draft=draft, used=False, error=f"{type(e).__name__}: {e}")


def _enrich(doc: SourceDoc, draft: DraftForm) -> LlmResult:
    s = get_settings()
    if not s.llm_enabled:
        return LlmResult(draft=draft, used=False, error="LLM wyłączony (LLM_ENABLED=false)")
    batches = build_batches(doc, draft)
    if not batches:
        return LlmResult(draft=draft, used=False, model=s.llm_model)
    deadline = time.monotonic() + s.llm_timeout_s
    responses: list[dict[str, Any]] = []
    errors: list[str] = []
    for b in batches:
        try:
            responses.append(
                client.chat_json(
                    base_url=s.ollama_url,
                    model=s.llm_model,
                    system=b.system,
                    user=b.user,
                    schema=b.schema,
                    deadline=deadline,
                )
            )
        except client.LlmError as e:
            errors.append(str(e))
            if time.monotonic() >= deadline:
                break
    error = "; ".join(errors) if errors else None
    if not responses:
        return LlmResult(draft=draft, used=False, model=s.llm_model, error=error)
    out = draft.model_copy(deep=True)
    changes = fuse(out, responses)
    log.info("LLM enrich: %d zmian (%d/%d wywołań OK)", len(changes), len(responses), len(batches))
    return LlmResult(draft=out, used=True, model=s.llm_model, error=error)
