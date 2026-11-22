from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .limits import BodyLimitMiddleware
from .routes import router

WEB_DIR = Path(os.environ.get("WEB_DIR", Path(__file__).resolve().parents[2] / "web"))


def create_app() -> FastAPI:
    app = FastAPI(
        title="FormProof API",
        version="0.1.0",
        description="Konwersja formularzy (PDF/obraz/DOCX/DOC/XLSX/ODS) do JSON kreatora eUsług COI "
        "z dowodem pochodzenia pól, walidacją reguł COI i auto-naprawą.",
        docs_url="/docs",
        openapi_url="/openapi.json",
    )

    @app.exception_handler(HTTPException)
    async def _http(_: Request, exc: HTTPException) -> JSONResponse:
        body = exc.detail if isinstance(exc.detail, dict) else {"code": "INTERNAL", "message": str(exc.detail)}
        return JSONResponse(status_code=exc.status_code, content=body, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def _val(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"code": "INVALID_REQUEST", "message": "Niepoprawne żądanie."})

    app.add_middleware(BodyLimitMiddleware)
    app.include_router(router)
    if (WEB_DIR / "index.html").exists():
        app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
    return app


app = create_app()
