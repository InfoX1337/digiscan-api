"""STUB – runda 2 (DICT): słowniki, dane inicjalne, propozycje słowników."""

from __future__ import annotations

from ..types.draft import DraftForm
from ..types.stages import DictResult


def apply_dictionaries(draft: DraftForm) -> DictResult:
    return DictResult(draft=draft)


def list_dictionaries() -> list[dict[str, object]]:
    return []


def get_dictionary(name: str) -> list[str] | None:
    return None
