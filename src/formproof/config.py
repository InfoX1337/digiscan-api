"""Konfiguracja wyłącznie z env (parametry integracyjne w jednym miejscu)."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_CLIENT_SECRET = "demo-secret"  # noqa: S105 – konto demo tylko dev
DEV_SECRET = "dev-secret-change-me-dev-secret-change-me"  # noqa: S105 – tylko dev; produkcja wymaga JWT_SECRET


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: str = Field(default="development", alias="APP_ENV")
    port: int = 8000
    host: str = "0.0.0.0"  # noqa: S104 – kontener
    log_level: str = "info"

    max_file_bytes: int = 15 * 1024 * 1024
    max_batch_files: int = 10
    max_ocr_pages: int = 5
    request_timeout_s: float = 120.0

    jwt_secret: str = DEV_SECRET
    jwt_expires_s: int = 3600
    jwt_issuer: str = "formproof"
    jwt_audience: str = "formproof-api"

    auth_client_id: str = "demo"
    auth_client_secret: str = DEV_CLIENT_SECRET  # konto demo (README); produkcja wymaga AUTH_CLIENT_SECRET

    llm_enabled: bool = True
    ollama_url: str = "http://localhost:11434"
    llm_model: str = "qwen3.5:4b"
    llm_timeout_s: float = 45.0

    tesseract_cmd: str = "tesseract"
    demo_ui: bool = True  # UI w trybie demo pobiera token automatycznie

    @field_validator("jwt_secret")
    @classmethod
    def _secret_len(cls, v: str) -> str:
        if len(v) < 32:
            raise ValueError("JWT_SECRET musi mieć >= 32 znaki")
        return v


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    if s.env == "production" and s.jwt_secret == DEV_SECRET:
        raise RuntimeError("Produkcja wymaga ustawienia JWT_SECRET (>= 32 znaki).")
    if s.env == "production" and s.auth_client_secret == DEV_CLIENT_SECRET:
        raise RuntimeError("Produkcja wymaga ustawienia AUTH_CLIENT_SECRET (nie domyślnego).")
    if s.env == "production" and s.demo_ui:
        raise RuntimeError("DEMO_UI=true niedozwolone przy APP_ENV=production.")
    return s
