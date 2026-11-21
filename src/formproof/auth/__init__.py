"""JWT (HS256): wydawanie tokenu dla klienta z env i weryfikacja Bearer."""

from __future__ import annotations

import hmac
import time
from typing import Annotated, Any

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ..config import Settings, get_settings

_bearer = HTTPBearer(auto_error=False)


def check_client(cfg: Settings, client_id: str, client_secret: str) -> bool:
    ok_id = hmac.compare_digest(client_id.encode(), cfg.auth_client_id.encode())
    ok_secret = hmac.compare_digest(client_secret.encode(), cfg.auth_client_secret.encode())
    return ok_id and ok_secret


def issue_token(cfg: Settings, subject: str, expires_s: int | None = None) -> tuple[str, int]:
    now = int(time.time())
    ttl = expires_s if expires_s is not None else cfg.jwt_expires_s
    payload = {
        "sub": subject,
        "iat": now,
        "exp": now + ttl,
        "iss": cfg.jwt_issuer,
        "aud": cfg.jwt_audience,
    }
    return jwt.encode(payload, cfg.jwt_secret, algorithm="HS256"), ttl


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"code": "UNAUTHORIZED", "message": "Brak lub nieważny token JWT."},
        headers={"WWW-Authenticate": "Bearer"},
    )


def require_jwt(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    cfg: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    if creds is None or creds.scheme.lower() != "bearer":
        raise _unauthorized()
    try:
        claims: dict[str, Any] = jwt.decode(
            creds.credentials,
            cfg.jwt_secret,
            algorithms=["HS256"],
            audience=cfg.jwt_audience,
            issuer=cfg.jwt_issuer,
            options={"require": ["exp", "iat", "sub"]},
        )
    except jwt.PyJWTError as e:
        raise _unauthorized() from e
    return claims
