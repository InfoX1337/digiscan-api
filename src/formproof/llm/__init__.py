"""LLM (R1): opcjonalne wzbogacenie DraftForm przez lokalny model Ollama. Nigdy nie rzuca."""

from __future__ import annotations

import logging
import re
import time
from typing import Any

from ..config import get_settings
from ..types.draft import DraftForm
from ..types.source import SourceDoc
from ..types.stages import LlmResult
from . import client, structure
from .fusion import fuse
from .prompt import build_batches

log = logging.getLogger(__name__)

__all__ = ["enrich"]

STRUCTURE_TOKENS = 2048
_TRANSPORT = re.compile(
    r"timed out|timeout|limit czasu|URLError|Connection|refused|Name or service", re.I
)  # struktura całego formularza w formacie liniowym


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
    deadline = time.monotonic() + s.llm_timeout_s
    errors: list[str] = []
    used = False
    created: set[str] = set()
    # 1) struktura: sekcje i pola części wypełnianej przez wnioskodawcę (każde pole ugruntowane w dokumencie)
    p = structure.build_prompt(doc, draft)
    try:
        resp = client.chat_json(
            base_url=s.ollama_url,
            model=s.llm_model,
            system=p.system,
            user=p.user,
            schema=p.schema,
            deadline=deadline,
            num_predict=STRUCTURE_TOKENS,
        )
        st = structure.apply(doc, draft, resp)
        log.info("LLM structure: %s", "; ".join(st.changes[-6:]))
        used = True
        if st.applied:
            draft, created = st.draft, st.created
    except client.LlmError as e:
        errors.append(f"struktura: {e}")
        if _TRANSPORT.search(str(e)):  # Ollama niedostępna / zbyt wolna – nie próbujemy kroku 2
            return LlmResult(draft=draft, used=False, model=s.llm_model, error=str(e))
    # 2) ocena pojedynczych niepewnych pól (poza utworzonymi w kroku 1)
    batches = build_batches(doc, draft, exclude=created)
    if not batches or time.monotonic() >= deadline - 1:
        return LlmResult(draft=draft, used=used, model=s.llm_model, error="; ".join(errors) or None)
    responses: list[dict[str, Any]] = []
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
        return LlmResult(draft=draft, used=used, model=s.llm_model, error=error)
    out = draft.model_copy(deep=True)
    changes = fuse(out, responses)
    log.info("LLM enrich: %d zmian (%d/%d wywołań OK)", len(changes), len(responses), len(batches))
    return LlmResult(draft=out, used=True, model=s.llm_model, error=error)
