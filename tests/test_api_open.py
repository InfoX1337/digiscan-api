"""Domyślny tryb demo: API bez JWT."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from formproof.app import create_app
from formproof.config import get_settings


@pytest.fixture
def open_client(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    monkeypatch.setenv("AUTH_ENABLED", "false")
    get_settings.cache_clear()
    with TestClient(create_app()) as c:
        yield c
    monkeypatch.undo()
    get_settings.cache_clear()


def test_open_api_needs_no_token(open_client) -> None:  # type: ignore[no-untyped-def]
    assert open_client.get("/api/v1/dictionaries").status_code == 200
    r = open_client.post("/api/v1/forms/convert", files={"file": ("a.xyz", b"x")})
    assert r.status_code != 401


def test_demo_config_open(open_client) -> None:  # type: ignore[no-untyped-def]
    assert open_client.get("/api/v1/demo-config").json()["authRequired"] is False
