"""Budowa promptów i JSON-schemy odpowiedzi (po polsku, bez hardkodu pod konkretne formularze)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..types.draft import DraftField, DraftForm, iter_draft
from ..types.form import VALIDATORS
from ..types.source import SourceDoc

MAX_TEXT_CHARS = 6000
MAX_FIELDS_PER_BATCH = 14
MAX_BATCHES = 3
MAX_CANDIDATES = 28  # najniższa pewność najpierw; limit czasu generacji
CANDIDATE_BELOW = 0.8  # pola o niższej pewności idą do LLM
CHOICE_TYPES = frozenset({"RADIO", "SELECT", "CHECKBOX"})

DICTIONARIES: tuple[str, ...] = ("Kraje", "Województwo", "Powiat", "Gmina", "Miejscowość", "Numery kierunkowe")
FORMAT_VALIDATORS: tuple[str, ...] = tuple(v for v in VALIDATORS if v != "REQUIRED")

SYSTEM = (
    "Jesteś ekspertem od cyfryzacji polskich formularzy urzędowych do e-usług. "
    "Dostajesz tekst formularza i listę pól wykrytych regułami. Dla każdego pola z listy oceń: "
    "typ pola, walidatory formatu, słownik (jeśli wartość pochodzi z listy), poprawny tytuł "
    "(dla sekcji) oraz zależność wyświetlania, gdy tekst mówi 'jeśli', 'w przypadku', 'dotyczy tylko'. "
    "Bądź zachowawczy: jeśli pole jest poprawne, zwróć jego obecne wartości. Nie wymyślaj pól. "
    "Typy: TEXT_FIELD (krótki tekst), TEXTAREA (dłuższy opis), NUMBER (liczba/kwota), DATEPICKER (data), "
    "SELECT (lista/słownik), RADIO (jeden z kilku), CHECKBOX (zaznaczenie), FILE_UPLOADER (załącznik), "
    "SECTION (grupa pól), BRAK (to nie jest pole do wypełnienia: tekst nadrukowany, dane urzędu, "
    "fragment zdania lub szum OCR). Walidatory: PESEL, NIP, REGON, EMAIL, ZIP_CODE (kod pocztowy), EPUAP, ADE, "
    "SERIAL_NUMBER_ID_CARD (seria i numer dowodu). Słowniki: " + ", ".join(DICTIONARIES) + ". "
    "Odpowiadaj wyłącznie JSON-em zgodnym ze schemą."
)


@dataclass
class Batch:
    keys: list[str]
    system: str
    user: str
    schema: dict[str, Any]
    with_title: bool


def doc_text(doc: SourceDoc, limit: int = MAX_TEXT_CHARS) -> str:
    parts: list[str] = []
    size = 0
    for b in doc.blocks:
        t = " ".join(b.text.split())
        if not t:
            continue
        if b.kind == "checkbox":
            t = "[ ] " + t
        if size + len(t) + 1 > limit:
            parts.append("…(obcięto)")
            break
        parts.append(t)
        size += len(t) + 1
    return "\n".join(parts)


def all_fields(draft: DraftForm) -> list[DraftField]:
    return [f for tab in draft.tabs for f in iter_draft(tab.fields)]


def candidates(draft: DraftForm) -> list[DraftField]:
    out: list[DraftField] = []
    for f in all_fields(draft):
        if f.type in ("TEXT_BLOCK", "INFO_SECTION", "CONSENT_SECTION", "REPEATING_SECTION"):
            continue
        if f.confidence < CANDIDATE_BELOW:
            out.append(f)
    out.sort(key=lambda f: f.confidence)  # stabilne: przy remisie kolejność dokumentu
    return out[:MAX_CANDIDATES]


def _line(f: DraftField) -> str:
    bits = [f"{f.key} | {f.type} | {f.title[:120]}"]
    vals = [v for v in f.validation if v != "REQUIRED"]
    if vals:
        bits.append("walidatory=" + ",".join(vals))
    if f.dictionary_name:
        bits.append("słownik=" + f.dictionary_name)
    if f.options:
        bits.append("opcje=" + "; ".join(o.name[:60] for o in f.options[:8]))
    if f.show_when:
        sw = f.show_when[0]
        bits.append(f"pokaż_gdy={sw.when_key}{'!=' if sw.negate else '='}{sw.equals}")
    bits.append(f"pewność={f.confidence:.2f}")
    return " | ".join(bits)


def _schema(with_title: bool) -> dict[str, Any]:
    """Każde pole = jedna linia tekstu (zwięźle: generacja dominuje czas na małym modelu)."""
    props: dict[str, Any] = {"fields": {"type": "array", "items": {"type": "string"}}}
    required = ["fields"]
    if with_title:
        props["form_title"] = {"type": "string"}
        required.insert(0, "form_title")
    return {"type": "object", "properties": props, "required": required}


LINE_FORMAT = (
    "Dla każdego pola do oceny zwróć w `fields` jeden napis w formacie "
    "'klucz;TYP;WALIDATOR;SŁOWNIK;TYTUŁ;ZALEŻNOŚĆ' (puste elementy zostaw puste), gdzie: "
    "TYP – jeden z typów; WALIDATOR – jeden walidator formatu lub pusto; SŁOWNIK – nazwa słownika lub pusto; "
    "TYTUŁ – poprawiony tytuł tylko dla SECTION, inaczej pusto; ZALEŻNOŚĆ – 'klucz_sterujący=opcja' lub "
    "'klucz_sterujący!=opcja' tylko gdy tekst ją opisuje, inaczej pusto. "
    "Przykład: 'f9;TEXT_FIELD;EMAIL;;;' albo 'f3;SECTION;;;Dane adresowe;f2=Tak'."
)


def build_batches(doc: SourceDoc, draft: DraftForm) -> list[Batch]:
    cands = candidates(draft)
    want_title = draft.title_confidence < CANDIDATE_BELOW
    if not cands and not want_title:
        return []
    fields = all_fields(draft)
    controllers = [f for f in fields if f.type in CHOICE_TYPES and f.options]
    ctrl_lines = "\n".join(_line(f) for f in controllers[:20]) or "(brak)"
    text = doc_text(doc)
    chunks = [cands[i : i + MAX_FIELDS_PER_BATCH] for i in range(0, len(cands), MAX_FIELDS_PER_BATCH)][:MAX_BATCHES]
    if not chunks:
        chunks = [[]]
    batches: list[Batch] = []
    for i, chunk in enumerate(chunks):
        with_title = want_title and i == 0
        user = (
            f"TYTUŁ WYKRYTY: {draft.title}\n\n"
            f"TEKST FORMULARZA:\n{text}\n\n"
            f"POLA STERUJĄCE (możliwe źródła zależności):\n{ctrl_lines}\n\n"
            "POLA DO OCENY (klucz | typ | tytuł | ...):\n"
            + ("\n".join(_line(f) for f in chunk) or "(brak)")
            + "\n\n"
            + LINE_FORMAT
            + (" W `form_title` podaj właściwy tytuł formularza." if with_title else "")
        )
        schema = _schema(with_title)
        batches.append(
            Batch(keys=[f.key for f in chunk], system=SYSTEM, user=user, schema=schema, with_title=with_title)
        )
    return batches
