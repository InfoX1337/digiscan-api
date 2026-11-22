from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

os.environ["APP_ENV"] = "test"
os.environ["LLM_ENABLED"] = "false"
os.environ["AUTH_ENABLED"] = "true"  # testy JWT; tryb otwarty testuje test_api_open.py

FIXTURES = Path(__file__).parent / "fixtures"
MATERIALS = FIXTURES / "materials"


def find_material(ext: str) -> Path | None:
    """Pierwszy plik o rozszerzeniu z materiałów COI (symlink do .work/mat, poza gitem)."""
    if not MATERIALS.exists():
        return None
    for p in sorted(MATERIALS.rglob(f"*.{ext}")):
        if "Materiały do zadania" not in str(p):
            return p
    return None


@pytest.fixture
def client() -> Iterator[object]:
    from fastapi.testclient import TestClient

    from formproof.app import create_app

    with TestClient(create_app()) as c:
        yield c


@pytest.fixture
def token(client) -> str:  # type: ignore[no-untyped-def]
    r = client.post("/api/v1/auth/token", json={"clientId": "demo", "clientSecret": "demo-secret"})
    return str(r.json()["accessToken"])
