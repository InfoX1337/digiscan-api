"""E2E API na materiałach COI (4 formularze x formaty). Pomijane, gdy brak materiałów.

Pliki nie pasują do domyślnego wzorca test_*.py – uruchomienie jawne:
    uv run pytest tests/e2e/api_test_materials.py
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from tests.conftest import MATERIALS

MIME = {
    "pdf": "application/pdf",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "doc": "application/msword",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "ods": "application/vnd.oasis.opendocument.spreadsheet",
}


def _materials() -> list[Path]:
    if not MATERIALS.exists():
        return []
    return [
        p
        for p in sorted(MATERIALS.rglob("*"))
        if p.is_file()
        and p.suffix.lower().lstrip(".") in MIME
        and "Materiały do zadania dla Uczestników" not in str(p.relative_to(MATERIALS))
        and "wizualizacja" not in p.name.casefold()
    ]


FILES = _materials()
pytestmark = pytest.mark.skipif(not FILES, reason="materiały poza repo")


def _hdr(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _upload(p: Path) -> tuple[str, bytes, str]:
    return (p.name, p.read_bytes(), MIME[p.suffix.lower().lstrip(".")])


def _assert_ok(body: dict[str, Any]) -> None:
    form, report = body["form"], body["report"]
    assert form["title"] and form["tabs"]
    assert "confidence" not in str(form) and "source" not in form
    assert report["fields"], "brak pól w raporcie"
    assert 0 <= report["confidence"] <= 1
    assert all(0 <= f["confidence"] <= 1 for f in report["fields"].values())
    failing = [r["id"] for r in report["rules"] if r["severity"] == "error" and not r["passed"]]
    assert not failing, f"reguły error nie przechodzą po naprawie: {failing}"


@pytest.mark.parametrize("path", FILES, ids=[f"{p.parent.parent.name[:2]}{p.name}" for p in FILES])
def test_convert_material(client, token: str, path: Path) -> None:  # type: ignore[no-untyped-def]
    r = client.post("/api/v1/forms/convert?llm=false", headers=_hdr(token), files={"file": _upload(path)})
    assert r.status_code == 200, r.text
    _assert_ok(r.json())


def test_batch_three_files(client, token: str) -> None:  # type: ignore[no-untyped-def]
    picks = [p for p in FILES if p.suffix.lower() == ".pdf"][:3] or FILES[:3]
    assert len(picks) == 3
    r = client.post(
        "/api/v1/forms/convert/batch?llm=false",
        headers=_hdr(token),
        files=[("file", _upload(p)) for p in picks],
    )
    assert r.status_code == 200, r.text
    results = r.json()["results"]
    assert [x["filename"] for x in results] == [p.name for p in picks]
    for x in results:
        assert x["ok"], x
        _assert_ok(x)


def test_batch_requires_jwt(client) -> None:  # type: ignore[no-untyped-def]
    r = client.post("/api/v1/forms/convert/batch", files=[("file", ("a.pdf", b"x", "application/pdf"))])
    assert r.status_code == 401


def test_convert_401_without_token(client) -> None:  # type: ignore[no-untyped-def]
    p = FILES[0]
    r = client.post("/api/v1/forms/convert", files={"file": _upload(p)})
    assert r.status_code == 401
    assert r.json()["code"] == "UNAUTHORIZED"


def test_convert_401_bad_token(client) -> None:  # type: ignore[no-untyped-def]
    r = client.post("/api/v1/forms/convert", headers=_hdr("zly.token.x"), files={"file": _upload(FILES[0])})
    assert r.status_code == 401


def test_bad_extension_400(client, token: str) -> None:  # type: ignore[no-untyped-def]
    r = client.post(
        "/api/v1/forms/convert",
        headers=_hdr(token),
        files={"file": ("virus.exe", b"MZ\x00\x00", "application/octet-stream")},
    )
    assert r.status_code in (400, 415)  # API zwraca 415 dla nieobsługiwanego typu
    assert r.json()["code"] == "BAD_EXTENSION"
