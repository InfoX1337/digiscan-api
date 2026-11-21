from __future__ import annotations

import time
from pathlib import Path

import pytest

from formproof.extract import extract
from formproof.extract.common import segment
from formproof.types.source import SourceDoc, SourceFormat
from formproof.types.stages import ExtractInput

from ..conftest import MATERIALS

needs_mat = pytest.mark.skipif(not MATERIALS.exists(), reason="brak materiałów")

FORMS = {
    "1": "Wniosek o ustalenie numeru porządkowego nieruchomości",
    "2": "Wniosek o zwrot opłaty skarbowej",
    "3": "Wniosek o wydanie zaświadczenia",
    "4": "Wniosek o wynajęcie świetlicy",
}


def _find(num: str, ext: str) -> Path | None:
    if not MATERIALS.exists():
        return None
    for p in sorted(MATERIALS.rglob(f"{FORMS[num]}.{ext}")):
        if "Materiały do zadania" not in str(p):
            return p
    return None


def _run(num: str, ext: str, fmt: SourceFormat) -> SourceDoc:
    p = _find(num, ext)
    if p is None:
        pytest.skip(f"brak {FORMS[num]}.{ext}")
    return extract(ExtractInput(p.name, fmt, p.read_bytes()))


def _text(doc: SourceDoc) -> str:
    return " ".join(b.text for b in doc.blocks).lower()


def _check_ids(doc: SourceDoc) -> None:
    ids = [b.id for b in doc.blocks]
    assert len(ids) == len(set(ids))
    assert all(b.id.startswith(f"p{b.page}-b") for b in doc.blocks)


def test_segment_checkbox_and_lines() -> None:
    segs = segment("Imię: ........... ☑ Tak ☐ Nie ____")
    kinds = [(s.kind, s.text, s.checked) for s in segs]
    assert kinds == [
        ("text", "Imię:", None),
        ("line", "", None),
        ("checkbox", "Tak", True),
        ("checkbox", "Nie", False),
        ("line", "", None),
    ]


def test_deadline_expired_warns() -> None:
    p = _find("1", "pdf")
    if p is None:
        pytest.skip("brak materiałów")
    doc = extract(ExtractInput(p.name, "pdf", p.read_bytes(), deadline=time.monotonic() - 1))
    assert doc.warnings
    assert not doc.blocks


@needs_mat
@pytest.mark.parametrize("num", ["1", "2", "3", "4"])
def test_pdf(num: str) -> None:
    doc = _run(num, "pdf", "pdf")
    assert len(doc.blocks) >= 20
    assert not doc.ocr
    assert doc.pages and doc.pages[0].width
    assert all(b.bbox is not None for b in doc.blocks)
    assert any(b.kind == "line" for b in doc.blocks)
    _check_ids(doc)


@needs_mat
def test_pdf_checkboxes_and_words() -> None:
    doc = _run("2", "pdf", "pdf")
    labels = [b.text for b in doc.blocks if b.kind == "checkbox"]
    assert any("Gotówką" in lbl for lbl in labels)
    assert "wnioskodawcy" in _text(doc)
    doc1 = _run("1", "pdf", "pdf")
    assert "wnioskodawca" in _text(doc1)


@needs_mat
@pytest.mark.parametrize("num", ["1", "2", "3", "4"])
def test_docx(num: str) -> None:
    doc = _run(num, "docx", "docx")
    assert len(doc.blocks) >= 20
    _check_ids(doc)


@needs_mat
def test_docx_content() -> None:
    assert "wnioskodawc" in _text(_run("1", "docx", "docx"))
    assert "pesel" in _text(_run("3", "docx", "docx")) or len(_run("3", "docx", "docx").blocks) > 20


@needs_mat
@pytest.mark.parametrize("num", ["1", "2", "3", "4"])
def test_doc(num: str) -> None:
    doc = _run(num, "doc", "doc")
    assert len(doc.blocks) >= 20
    assert any("tylko tekst" in w for w in doc.warnings)
    _check_ids(doc)


@needs_mat
@pytest.mark.parametrize("ext", ["xlsx", "ods"])
@pytest.mark.parametrize("num", ["1", "2", "3", "4"])
def test_sheets(num: str, ext: str) -> None:
    doc = _run(num, ext, ext)  # type: ignore[arg-type]
    assert len(doc.blocks) >= 20
    assert doc.pages and doc.pages[0].name
    assert all(b.row is not None and b.col is not None for b in doc.blocks if b.kind == "cell")
    _check_ids(doc)


@needs_mat
def test_xlsx_ods_agree() -> None:
    a, b = _run("2", "xlsx", "xlsx"), _run("2", "ods", "ods")
    assert abs(len(a.blocks) - len(b.blocks)) <= 3


@needs_mat
@pytest.mark.parametrize("num", ["1", "2", "3", "4"])
def test_image_ocr(num: str) -> None:
    doc = _run(num, "jpg", "image")
    assert doc.ocr
    if any("OCR niedostępny" in w for w in doc.warnings):
        pytest.skip("brak tesseract")
    assert len(doc.blocks) >= 20
    assert all(0 <= b.confidence <= 1 for b in doc.blocks)
    _check_ids(doc)


def test_unsupported_image_without_tesseract_does_not_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    import io

    from PIL import Image

    import formproof.extract.ocr as ocr

    monkeypatch.setattr(ocr, "pick_lang", lambda w: (w.append("OCR niedostępny: test"), None)[1])
    buf = io.BytesIO()
    Image.new("RGB", (50, 50), "white").save(buf, "PNG")
    doc = extract(ExtractInput("a.png", "image", buf.getvalue()))
    assert doc.ocr and doc.warnings and not doc.blocks
