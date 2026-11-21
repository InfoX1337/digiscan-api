"""Klient Ollama (`/api/chat`, structured output). Tylko stdlib; 1 równoległe wywołanie; cache in-memory."""

from __future__ import annotations

import hashlib
import json
import threading
import time
import urllib.error
import urllib.request
from collections import OrderedDict
from typing import Any

CACHE_MAX = 128

_lock = threading.Lock()  # max 1 równoległe wywołanie LLM w procesie
_cache: OrderedDict[str, dict[str, Any]] = OrderedDict()
_cache_lock = threading.Lock()


class LlmError(Exception):
    """Błąd wywołania LLM (sieć, timeout, zły JSON)."""


def post_json(url: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    """Transport HTTP (podmieniany w testach)."""
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")  # noqa: S310 – URL z configu
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        body = json.loads(resp.read().decode("utf-8"))
    if not isinstance(body, dict):
        raise LlmError("odpowiedź Ollama nie jest obiektem JSON")
    return body


def cache_key(model: str, system: str, user: str, schema: dict[str, Any]) -> str:
    raw = json.dumps([model, system, user, schema], ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def cache_clear() -> None:
    with _cache_lock:
        _cache.clear()


def _cache_get(key: str) -> dict[str, Any] | None:
    with _cache_lock:
        val = _cache.get(key)
        if val is not None:
            _cache.move_to_end(key)
        return val


def _cache_put(key: str, val: dict[str, Any]) -> None:
    with _cache_lock:
        _cache[key] = val
        _cache.move_to_end(key)
        while len(_cache) > CACHE_MAX:
            _cache.popitem(last=False)


def _parse_content(body: dict[str, Any]) -> dict[str, Any]:
    msg = body.get("message")
    content = msg.get("content") if isinstance(msg, dict) else None
    if not isinstance(content, str) or not content.strip():
        raise LlmError("pusta odpowiedź modelu")
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as e:
        raise LlmError(f"niepoprawny JSON z modelu: {e.msg}") from e
    if not isinstance(parsed, dict):
        raise LlmError("odpowiedź modelu nie jest obiektem JSON")
    return parsed


def chat_json(
    *,
    base_url: str,
    model: str,
    system: str,
    user: str,
    schema: dict[str, Any],
    deadline: float,
    retries: int = 1,
) -> dict[str, Any]:
    """Wywołanie z JSON-schemą; rzuca LlmError. `deadline` = time.monotonic() granica całkowita."""
    key = cache_key(model, system, user, schema)
    hit = _cache_get(key)
    if hit is not None:
        return hit
    payload: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "format": schema,
        "stream": False,
        "think": False,
        "options": {"temperature": 0, "num_ctx": 8192},
    }
    url = base_url.rstrip("/") + "/api/chat"
    remaining = deadline - time.monotonic()
    if remaining <= 0 or not _lock.acquire(timeout=remaining):
        raise LlmError("przekroczono limit czasu oczekiwania na LLM")
    try:
        last: Exception | None = None
        for _ in range(retries + 1):
            remaining = deadline - time.monotonic()
            if remaining <= 0.5:
                break
            try:
                result = _parse_content(post_json(url, payload, remaining))
            except (LlmError, OSError, urllib.error.URLError, ValueError) as e:
                last = e
                continue
            _cache_put(key, result)
            return result
        if last is None:
            raise LlmError("przekroczono limit czasu LLM")
        if isinstance(last, LlmError):
            raise last
        raise LlmError(f"{type(last).__name__}: {last}")
    finally:
        _lock.release()
