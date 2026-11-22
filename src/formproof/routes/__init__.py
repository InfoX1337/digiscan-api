"""API v1 (FastAPI). Domyślnie otwarte (demo); z AUTH_ENABLED=true wymagają JWT Bearer (poza /auth/token i /health)."""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, File, Query, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError

from .. import dictionaries as dict_mod
from .. import validate as validate_mod
from ..auth import check_client, issue_token, require_jwt
from ..config import Settings, get_settings
from ..ingest import IngestError, ingest
from ..pipeline import ConvertOptions, Timeout, convert

log = logging.getLogger("formproof")

router = APIRouter(prefix="/api/v1")
Cfg = Annotated[Settings, Depends(get_settings)]
Auth = Annotated[dict[str, Any], Depends(require_jwt)]


def err(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"code": code, "message": message})


def _to_error(e: Exception) -> tuple[int, str, str]:
    if isinstance(e, IngestError):
        return e.status, e.code, e.message
    if isinstance(e, Timeout):
        return 504, "TIMEOUT", "Przekroczono czas przetwarzania."
    log.exception("convert failed")
    return 500, "INTERNAL", "Błąd przetwarzania pliku."


class TokenRequest(BaseModel):
    clientId: str = Field(max_length=200)  # noqa: N815 – kontrakt API
    clientSecret: str = Field(max_length=200)  # noqa: N815


@router.post("/auth/token", tags=["auth"])
def token(body: TokenRequest, cfg: Cfg) -> Any:
    if not check_client(cfg, body.clientId, body.clientSecret):
        return err(401, "UNAUTHORIZED", "Niepoprawne dane klienta.")
    tok, exp = issue_token(cfg, body.clientId)
    return {"accessToken": tok, "tokenType": "Bearer", "expiresIn": exp}


@router.get("/health", tags=["system"])
def health(cfg: Cfg) -> dict[str, Any]:
    return {"status": "ok", "llm": {"enabled": cfg.llm_enabled, "model": cfg.llm_model}}


async def _read(upload: UploadFile, cfg: Settings) -> bytes:
    data = await upload.read(cfg.max_file_bytes + 1)
    if len(data) > cfg.max_file_bytes:
        raise IngestError("FILE_TOO_LARGE", f"Plik przekracza limit {cfg.max_file_bytes // (1024 * 1024)} MB.", 413)
    return data


@router.post("/forms/convert", tags=["forms"])
async def convert_one(
    _: Auth,
    cfg: Cfg,
    file: Annotated[UploadFile | None, File(description="Formularz: pdf, doc, docx, ods, xlsx, jpg, jpeg, png")] = None,
    llm: Annotated[bool, Query(description="Wzbogacenie lokalnym LLM")] = True,
    previews: Annotated[bool, Query(description="Dołącz PNG stron oryginału do report.previews")] = False,
) -> Any:
    try:
        if file is None:
            raise IngestError("NO_FILE", 'Brak pliku w polu "file".')
        f = ingest(file.filename, await _read(file, cfg), cfg.max_file_bytes, file.content_type)
        res = await run_in_threadpool(convert, f, cfg, ConvertOptions(llm=llm, previews=previews))
        return res.dump()
    except Exception as e:  # noqa: BLE001
        return err(*_to_error(e))


@router.post("/forms/convert/batch", tags=["forms"])
async def convert_batch(
    _: Auth,
    cfg: Cfg,
    file: Annotated[list[UploadFile] | None, File(description="Wiele plików w polu file")] = None,
    llm: bool = True,
) -> Any:
    files = file or []
    if not files:
        return err(400, "NO_FILE", 'Brak plików w polu "file".')
    if len(files) > cfg.max_batch_files:
        return err(400, "TOO_MANY_FILES", f"Maksymalnie {cfg.max_batch_files} plików w jednym żądaniu.")
    results: list[dict[str, Any]] = []
    for up in files:
        try:
            f = ingest(up.filename, await _read(up, cfg), cfg.max_file_bytes, up.content_type)
            res = await run_in_threadpool(convert, f, cfg, ConvertOptions(llm=llm))
            results.append({"filename": up.filename, "ok": True, **res.dump()})
        except Exception as e:  # noqa: BLE001
            _status, code, msg = _to_error(e)
            results.append({"filename": up.filename, "ok": False, "error": {"code": code, "message": msg}})
    return {"results": results}


@router.post("/forms/validate", tags=["forms"])
def validate_form(_: Auth, form: Annotated[dict[str, Any], Body()], repair: bool = True) -> Any:
    from ..types.form import FormDefinition

    try:
        fd = FormDefinition.model_validate(form)
    except ValidationError as e:
        return err(422, "INVALID_FORM", f"Niepoprawna struktura formularza: {e.error_count()} błędów.")
    v = validate_mod.validate(fd, repair=repair)
    return {
        "form": v.form.dump(),
        "rules": [r.model_dump(mode="json", exclude_none=True) for r in v.rules],
        "repairs": [r.model_dump(mode="json", exclude_none=True) for r in v.repairs],
    }


@router.get("/dictionaries", tags=["dictionaries"])
def dictionaries(_: Auth) -> Any:
    return {"dictionaries": dict_mod.list_dictionaries()}


@router.get("/dictionaries/{name}", tags=["dictionaries"])
def dictionary(_: Auth, name: str) -> Any:
    items = dict_mod.get_dictionary(name)
    if items is None:
        return err(404, "NOT_FOUND", "Nieznany słownik.")
    return {"name": name, "items": items}


@router.get("/demo-config", include_in_schema=False)
def demo_config(cfg: Cfg) -> Any:
    if not cfg.auth_enabled:
        return {"demo": True, "authRequired": False}
    if not cfg.demo_ui:
        return {"demo": False, "authRequired": True}
    # Nigdy nie zwracamy sekretu klienta – tylko krótkożyciowy token demo (15 min).
    token, exp = issue_token(cfg, "demo-ui", expires_s=min(cfg.jwt_expires_s, 900))
    return {"demo": True, "authRequired": True, "accessToken": token, "expiresIn": exp}
