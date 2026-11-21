"""Strumień EXTRACT: dowolny format -> SourceDoc (kontrakt: types/stages.py ExtractFn)."""

from __future__ import annotations

from ..types.source import SourceDoc
from ..types.stages import ExtractInput


def extract(inp: ExtractInput) -> SourceDoc:
    fmt = inp.format
    if fmt == "pdf":
        from .pdf import extract_pdf

        return extract_pdf(inp)
    if fmt == "image":
        from .ocr import extract_image

        return extract_image(inp)
    from . import office

    if fmt == "docx":
        return office.extract_docx(inp)
    if fmt == "xlsx":
        return office.extract_xlsx(inp)
    if fmt == "ods":
        return office.extract_ods(inp)
    if fmt == "doc":
        return office.extract_doc(inp)
    raise ValueError(f"nieobsługiwany format: {fmt}")
