"""Wspólne narzędzia walidatora: przechodzenie po polach, slugi, identyfikatory."""

from __future__ import annotations

import re
import unicodedata
import uuid
from collections.abc import Iterator
from dataclasses import dataclass

from ..types.form import CONTAINER_TYPES, FormDefinition, FormField, Question

# Źródła reguł (odwołania w komunikatach).
SRC_RT = "Reguły techniczne konfiguracji formularzy i pól na formularzu"
SRC_JSON = "OpisImportowanegoPlikuJSON"
SRC_SCHEMA = "importowanyPlikJsonSchemat (schema.json)"
SRC_STD = "Standardy projektowania formularzy eUsług"
SRC_DICT = "Hacknation – Słowniki"

TECH_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")

INPUT_TYPES: frozenset[str] = frozenset(
    {
        "TEXT_FIELD",
        "TEXTAREA",
        "NUMBER",
        "DATEPICKER",
        "SELECT",
        "RADIO",
        "CHECKBOX",
        "FILE_UPLOADER",
        "CONSENT_SECTION",
    }
)
CHOICE_TYPES: frozenset[str] = frozenset({"SELECT", "RADIO", "CHECKBOX"})
FINISH_ALLOWED: frozenset[str] = frozenset({"INFO_SECTION", "TEXT_BLOCK"}) | CONTAINER_TYPES

_ID_NS = uuid.UUID("6f0f3a52-4c1e-4c8e-9a52-6b0b7f3f0c11")


@dataclass
class Node:
    """Pole w formularzu wraz z kontekstem (JSON Pointer, kontener, rodzic)."""

    tab_index: int
    path: str  # JSON Pointer do Question
    question: Question
    container: list[Question]
    parent: Question | None
    depth: int  # 0 = bezpośrednio na stronie

    @property
    def field(self) -> FormField:
        return self.question.field


def walk(form: FormDefinition) -> Iterator[Node]:
    for ti, tab in enumerate(form.tabs):
        yield from _walk(ti, f"/tabs/{ti}/questions", tab.questions, None, 0)


def _walk(ti: int, base: str, qs: list[Question], parent: Question | None, depth: int) -> Iterator[Node]:
    for i, q in enumerate(qs):
        path = f"{base}/{i}"
        yield Node(ti, path, q, qs, parent, depth)
        yield from _walk(ti, f"{path}/field/repeatingSectionGrid", q.field.repeating_section_grid, q, depth + 1)


def containers(form: FormDefinition) -> Iterator[tuple[str, list[Question]]]:
    """Wszystkie siatki: strony i niepuste `repeatingSectionGrid`."""
    for ti, tab in enumerate(form.tabs):
        yield f"/tabs/{ti}/questions", tab.questions
    for n in walk(form):
        if n.field.repeating_section_grid:
            yield f"{n.path}/field/repeatingSectionGrid", n.field.repeating_section_grid


def fold(text: str) -> str:
    """Małe litery bez polskich znaków diakrytycznych."""
    text = text.replace("ł", "l").replace("Ł", "L")
    norm = unicodedata.normalize("NFKD", text)
    return "".join(c for c in norm if not unicodedata.combining(c)).lower()


def slugify(text: str, fallback: str = "pole") -> str:
    s = re.sub(r"[^a-z0-9]+", "_", fold(text)).strip("_")
    if not s:
        s = fallback
    if not s[0].isalpha():
        s = f"{fallback}_{s}"
    return s[:80].rstrip("_")


def unique_name(base: str, taken: set[str]) -> str:
    if base not in taken:
        return base
    i = 2
    while f"{base}_{i}" in taken:
        i += 1
    return f"{base}_{i}"


def new_id(*parts: str) -> str:
    """Deterministyczny UUID (powtarzalne naprawy)."""
    return str(uuid.uuid5(_ID_NS, "|".join(parts)))


def has_input(q: Question) -> bool:
    return q.field.type in INPUT_TYPES or any(has_input(c) for c in q.field.repeating_section_grid)
