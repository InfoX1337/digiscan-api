"""Limit rozmiaru ciała żądania (ASGI), zanim multipart trafi do parsera i bufora tymczasowego.

Odrzuca żądanie z `Content-Length` ponad limit od razu, a przy transferze bez długości (chunked) przerywa
po przekroczeniu limitu w trakcie odczytu. Limit: pojedynczy plik + narzut multipart; batch: MAX_BATCH_BYTES.
"""

from __future__ import annotations

import json

from fastapi import HTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .config import get_settings

_MULTIPART_OVERHEAD = 64 * 1024
_JSON_LIMIT = 2 * 1024 * 1024  # /forms/validate, /auth/token


class _TooLarge(HTTPException):
    """HTTPException, żeby FastAPI nie zamieniał go na ogólne 400 przy parsowaniu ciała."""

    def __init__(self, limit: int) -> None:
        msg = f"Żądanie przekracza limit {limit // (1024 * 1024)} MB."
        super().__init__(status_code=413, detail={"code": "FILE_TOO_LARGE", "message": msg})


def _limit_for(path: str) -> int:
    cfg = get_settings()
    if path.endswith("/forms/convert/batch"):
        return cfg.max_batch_bytes
    if path.endswith("/forms/convert"):
        return cfg.max_file_bytes + _MULTIPART_OVERHEAD
    return _JSON_LIMIT


async def _reject(send: Send, limit: int) -> None:
    body = json.dumps(
        {"code": "FILE_TOO_LARGE", "message": f"Żądanie przekracza limit {limit // (1024 * 1024)} MB."},
        ensure_ascii=False,
    ).encode()
    await send(
        {
            "type": "http.response.start",
            "status": 413,
            "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
        }
    )
    await send({"type": "http.response.body", "body": body})


class BodyLimitMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method") not in ("POST", "PUT", "PATCH"):
            await self.app(scope, receive, send)
            return
        limit = _limit_for(scope.get("path", ""))
        headers: dict[bytes, bytes] = dict(scope.get("headers", []))
        try:
            declared = int(headers.get(b"content-length", b"-1"))
        except ValueError:
            declared = -1
        if declared > limit:
            await _reject(send, limit)
            return

        seen = 0
        started = False

        async def limited_receive() -> Message:
            nonlocal seen
            msg = await receive()
            if msg["type"] == "http.request":
                seen += len(msg.get("body", b""))
                if seen > limit:
                    raise _TooLarge(limit)
            return msg

        async def tracking_send(msg: Message) -> None:
            nonlocal started
            if msg["type"] == "http.response.start":
                started = True
            await send(msg)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except _TooLarge:
            if not started:
                await _reject(send, limit)


__all__ = ["BodyLimitMiddleware"]
