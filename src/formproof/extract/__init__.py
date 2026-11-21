"""STUB – strumień EXTRACT zastępuje implementacją (kontrakt: types/stages.py ExtractFn)."""

from __future__ import annotations

from ..types.source import SourceDoc, SourcePage
from ..types.stages import ExtractInput


def extract(inp: ExtractInput) -> SourceDoc:
    return SourceDoc(filename=inp.filename, format=inp.format, pages=[SourcePage(page=1)], warnings=["extract: stub"])
