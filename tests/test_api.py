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


@pytest.mark.parametrize("ch", list(";:><\\|'*%$/"))
def test_ingest_rejects_forbidden_chars(ch: str) -> None:
    with pytest.raises(IngestError) as e:
        ingest(f"wniosek{ch}1.pdf", PDF, 10**6)
    assert e.value.code == "BAD_FILENAME"


def test_ingest_name_length_limit_250() -> None:
    assert ingest("a" * 246 + ".pdf", PDF, 10**6).filename
    with pytest.raises(IngestError) as e:
        ingest("a" * 247 + ".pdf", PDF, 10**6)
    assert e.value.code == "BAD_FILENAME"


@pytest.mark.parametrize("ext", ["tif", "tiff", "xls", "odt"])
def test_ingest_rejects_extensions_outside_spec(ext: str) -> None:
    with pytest.raises(IngestError) as e:
        ingest(f"a.{ext}", PDF, 10**6)
    assert e.value.code == "BAD_EXTENSION"


@pytest.mark.parametrize(
    ("ctype", "ok"),
    [
        ("application/pdf", True),
        ("application/pdf; charset=binary", True),
        ("application/octet-stream", True),
        (None, True),
        ("image/png", False),
        ("text/plain", False),
    ],
)
def test_ingest_checks_declared_content_type(ctype: str | None, ok: bool) -> None:
    if ok:
        assert ingest("a.pdf", PDF, 10**6, ctype).ext == "pdf"
    else:
        with pytest.raises(IngestError) as e:
            ingest("a.pdf", PDF, 10**6, ctype)
        assert e.value.code == "MIME_MISMATCH"


def test_ingest_doc_requires_word_ole() -> None:
    ole = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 600
    with pytest.raises(IngestError) as e:
        ingest("a.doc", ole + "Workbook".encode("utf-16-le"), 10**6)
    assert e.value.code == "MIME_MISMATCH"
    assert ingest("a.doc", ole + "WordDocument".encode("utf-16-le"), 10**6).ext == "doc"


def test_convert_content_type_mismatch_via_api(client, token: str) -> None:  # type: ignore[no-untyped-def]
    r = client.post(
        "/api/v1/forms/convert",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("x.pdf", PDF, "image/png")},
    )
    assert r.status_code == 415
    assert r.json()["code"] == "MIME_MISMATCH"


def test_body_limit_content_length(client, token: str) -> None:  # type: ignore[no-untyped-def]
    from formproof.config import get_settings

    big = b"%PDF-" + b"0" * (get_settings().max_file_bytes + 128 * 1024)
    r = client.post(
        "/api/v1/forms/convert",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("big.pdf", big, "application/pdf")},
    )
    assert r.status_code == 413
    assert r.json()["code"] == "FILE_TOO_LARGE"


def test_body_limit_streamed_without_length(client, token: str) -> None:  # type: ignore[no-untyped-def]
    from formproof.config import get_settings

    limit = get_settings().max_batch_bytes

    def chunks():  # type: ignore[no-untyped-def]
        boundary = b'--b\r\nContent-Disposition: form-data; name="file"; filename="a.pdf"\r\n\r\n'
        yield boundary
        piece = b"0" * (1024 * 1024)
        for _ in range(limit // len(piece) + 2):
            yield piece

    r = client.post(
        "/api/v1/forms/convert/batch",
        headers={"Authorization": f"Bearer {token}", "content-type": "multipart/form-data; boundary=b"},
        content=chunks(),
    )
    assert r.status_code == 413
    assert r.json()["code"] == "FILE_TOO_LARGE"


def test_ingest_same_family_uses_content_format() -> None:
    """DOCX zapisany z rozszerzeniem .doc (realny plik urzędu) – przetwarzamy wg zawartości."""
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", "<w:document/>")
    f = ingest("wniosek.DOC", buf.getvalue(), 10**6)
    assert (f.ext, f.format, f.detected) == ("doc", "docx", "docx")
    with pytest.raises(IngestError) as e:
        ingest("a.doc", PDF, 10**6)  # inna rodzina – nadal odrzucone
    assert e.value.code == "MIME_MISMATCH"
