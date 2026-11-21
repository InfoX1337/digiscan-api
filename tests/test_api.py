import pytest

from formproof.ingest import IngestError, ingest

from .conftest import find_material

PDF = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"


def test_health(client) -> None:  # type: ignore[no-untyped-def]
    assert client.get("/api/v1/health").status_code == 200


def test_bad_secret(client) -> None:  # type: ignore[no-untyped-def]
    r = client.post("/api/v1/auth/token", json={"clientId": "demo", "clientSecret": "x"})
    assert r.status_code == 401


def test_convert_requires_jwt(client) -> None:  # type: ignore[no-untyped-def]
    r = client.post("/api/v1/forms/convert")
    assert r.status_code == 401
    assert r.json()["code"] == "UNAUTHORIZED"


def test_token(token: str) -> None:
    assert token.startswith("ey")


@pytest.mark.parametrize(
    ("name", "data", "code"),
    [
        ("a.exe", PDF, "BAD_EXTENSION"),
        ("a.pdf", b"", "EMPTY"),
        ("a.png", PDF, "MIME_MISMATCH"),
        ("../a.pdf", PDF, "BAD_FILENAME"),
    ],
)
def test_ingest_rejects(name: str, data: bytes, code: str) -> None:
    with pytest.raises(IngestError) as e:
        ingest(name, data, 10**6)
    assert e.value.code == code


def test_ingest_too_large() -> None:
    with pytest.raises(IngestError) as e:
        ingest("a.pdf", PDF, 10)
    assert e.value.code == "FILE_TOO_LARGE"


@pytest.mark.parametrize("ext", ["pdf", "png", "jpg", "jpeg", "docx", "doc", "xlsx", "ods"])
def test_real_materials_pass_ingest(ext: str) -> None:
    p = find_material(ext)
    if p is None:
        pytest.skip("materiały poza repo")
    assert ingest(p.name, p.read_bytes(), 15 * 2**20).ext == ext


def test_convert_mime_mismatch_via_api(client, token: str) -> None:  # type: ignore[no-untyped-def]
    r = client.post(
        "/api/v1/forms/convert",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("x.png", PDF, "application/octet-stream")},
    )
    assert r.status_code == 415
    assert r.json()["code"] == "MIME_MISMATCH"


def test_convert_stub_pipeline_422(client, token: str) -> None:  # type: ignore[no-untyped-def]
    p = find_material("pdf")
    if p is None:
        pytest.skip("materiały poza repo")
    r = client.post(
        "/api/v1/forms/convert",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": (p.name, p.read_bytes(), "application/pdf")},
    )
    # stub extract -> brak bloków -> 422; po EXTRACT -> 200
    assert r.status_code in (200, 422)
