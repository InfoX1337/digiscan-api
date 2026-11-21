"""Fuzja decyzji reguł i LLM. Zachowawczo: zgoda podnosi pewność, niezgoda nadpisuje tylko niską pewność."""

from __future__ import annotations

import re
import unicodedata
from typing import Any, cast

from ..types.draft import DraftField, DraftForm, Evidence, ShowWhen
from ..types.form import CONTAINER_TYPES, FIELD_TYPES, FieldType, Validator
from .prompt import CHOICE_TYPES, DICTIONARIES, FORMAT_VALIDATORS, all_fields

AGREE_CONF = 0.85  # zgoda reguł i LLM
OVERRIDE_BELOW = 0.6  # LLM nadpisuje decyzję reguł tylko poniżej tej pewności
LLM_CONF = 0.55  # decyzja przejęta od LLM – nadal poniżej progu przeglądu: człowiek zatwierdza
NOT_FIELD_CONF = 0.35  # LLM: to nie pole do wypełnienia (nadruk, adres urzędu, szum OCR)
ADD_BELOW = OVERRIDE_BELOW  # uzupełnienia (walidator/słownik/zależność) też tylko dla niepewnych pól

# typy, na które LLM może zmienić pole proste (bez opcji nie przechodzimy na RADIO/SELECT)
_SIMPLE = frozenset({"TEXT_FIELD", "TEXTAREA", "NUMBER", "DATEPICKER", "CHECKBOX", "FILE_UPLOADER"})


def fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.casefold())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join("".join(c if c.isalnum() else " " for c in s).split())


_BAD_TITLE = re.compile(r"[=|;]|pokaż_gdy|pewność|^f\d+\b|^(SECTION|TEXT_FIELD|BRAK)$", re.I)  # echo promptu
_DEP = re.compile(r"^\s*([^\s=!]+)\s*(!=|=)\s*(.+?)\s*$")


def normalize(item: Any) -> dict[str, Any] | None:
    """Linia 'klucz;TYP;WALIDATOR;SŁOWNIK;TYTUŁ;ZALEŻNOŚĆ' (lub gotowy dict) -> dict dla fuzji."""
    if isinstance(item, dict):
        return item
    if not isinstance(item, str) or ";" not in item:
        return None
    parts = [p.strip() for p in item.strip().strip("'\"").split(";")]
    parts += [""] * (6 - len(parts))
    key, typ, val, dic, title = parts[:5]
    dep = ";".join(parts[5:]).strip(" ;")
    out: dict[str, Any] = {"key": key, "type": typ.upper(), "dictionary": dic, "title": title}
    out["validators"] = [v.strip().upper() for v in val.split(",") if v.strip()]
    m = _DEP.match(dep) if dep else None
    if m:
        out["show_when_key"], out["show_when_equals"] = m.group(1), m.group(3)
        out["show_when_negate"] = m.group(2) == "!="
    return out


def _ev(reason: str) -> Evidence:
    return Evidence(by="llm", reason=reason)


def _type_allowed(f: DraftField, new: str) -> bool:
    if new not in FIELD_TYPES or new == f.type:
        return False
    if (f.type in CONTAINER_TYPES) != (new in CONTAINER_TYPES):
        return False  # nie przerabiamy sekcji na pole i odwrotnie (gubiłoby dzieci)
    if f.type in CONTAINER_TYPES:
        return False
    if new in ("RADIO", "SELECT"):
        return bool(f.options) or bool(f.dictionary_name)
    if f.type in CHOICE_TYPES and f.options and new not in CHOICE_TYPES:
        return False  # nie gubimy opcji
    return new in _SIMPLE


def _str(v: Any) -> str:
    return v.strip() if isinstance(v, str) else ""


def fuse_field(f: DraftField, s: dict[str, Any], by_key: dict[str, DraftField]) -> list[str]:
    """Modyfikuje `f` w miejscu. Zwraca listę opisów zmian (do logów/testów)."""
    changes: list[str] = []
    c0 = f.confidence
    agree = 0
    disagree = 0

    # --- typ ---
    new_type = _str(s.get("type"))
    if new_type == "BRAK" and f.type not in CONTAINER_TYPES:
        if c0 < AGREE_CONF:
            f.confidence = min(c0, NOT_FIELD_CONF)
            f.evidence.append(_ev("LLM: to raczej nie pole do wypełnienia (tekst nadrukowany lub szum OCR)"))
            changes.append("nie-pole")
        return changes
    if new_type == f.type:
        agree += 1
    elif new_type:
        disagree += 1
        if c0 < OVERRIDE_BELOW and _type_allowed(f, new_type):
            changes.append(f"typ {f.type}->{new_type}")
            f.evidence.append(_ev(f"LLM: typ {new_type} zamiast {f.type} (reguły niepewne {c0:.2f})"))
            f.type = cast(FieldType, new_type)
            f.confidence = LLM_CONF

    # --- słownik ---
    dic = _str(s.get("dictionary"))
    if dic and dic in DICTIONARIES and f.type not in CONTAINER_TYPES:
        if f.dictionary_name == dic:
            agree += 1
        elif f.dictionary_name is None and c0 < ADD_BELOW and f.type in ("TEXT_FIELD", "SELECT") and not f.options:
            f.dictionary_name = dic
            if f.type != "SELECT":
                changes.append(f"typ {f.type}->SELECT")
                f.type = "SELECT"
            changes.append(f"słownik {dic}")
            f.evidence.append(_ev(f"LLM: wartość ze słownika {dic}"))
            f.confidence = max(f.confidence, LLM_CONF)
        elif f.dictionary_name is not None:
            disagree += 1

    # --- walidatory (tylko dodawanie, nigdy usuwanie) ---
    raw_vals = s.get("validators")
    llm_vals = (
        [v for v in raw_vals if isinstance(v, str) and v in FORMAT_VALIDATORS] if isinstance(raw_vals, list) else []
    )
    have = {v for v in f.validation if v != "REQUIRED"}
    if f.type not in CONTAINER_TYPES and f.type in ("TEXT_FIELD", "NUMBER"):
        if have and have == set(llm_vals):
            agree += 1
        elif not have and llm_vals and c0 < ADD_BELOW:
            add = llm_vals[:1]  # jeden walidator formatu – zachowawczo
            f.validation = [*f.validation, *cast(list[Validator], add)]
            changes.append(f"walidator {add[0]}")
            f.evidence.append(_ev(f"LLM: walidator {add[0]} dla pola '{f.title}'"))
            f.confidence = max(f.confidence, LLM_CONF)

    # --- tytuł sekcji ---
    title = _str(s.get("title"))
    if f.type in CONTAINER_TYPES and title:
        if fold(title) == fold(f.title):
            agree += 1
        elif c0 < OVERRIDE_BELOW and 2 <= len(title) <= 200 and not _BAD_TITLE.search(title):
            changes.append(f"tytuł sekcji '{f.title}'->'{title}'")
            f.evidence.append(_ev(f"LLM: tytuł sekcji '{title}' zamiast '{f.title}'"))
            f.title = title
            f.confidence = max(f.confidence, LLM_CONF)

    # --- zależność (ShowWhen) – tylko gdy brak ---
    wk = _str(s.get("show_when_key"))
    eq = _str(s.get("show_when_equals"))
    if wk and eq:
        ctrl = by_key.get(wk)
        if f.show_when:
            if any(sw.when_key == wk for sw in f.show_when):
                agree += 1
        elif ctrl is not None and ctrl is not f and ctrl.type in CHOICE_TYPES and c0 < ADD_BELOW:
            names = {fold(o.name): o.name for o in ctrl.options}
            match = names.get(fold(eq))  # tylko istniejąca opcja pola sterującego
            if match is not None and not _is_ancestor(f, ctrl):
                neg = s.get("show_when_negate") is True
                f.show_when = [ShowWhen(when_key=wk, equals=match, negate=neg)]
                changes.append(f"zależność {wk}{'!=' if neg else '='}{match}")
                f.evidence.append(_ev(f"LLM: pokaż, gdy '{ctrl.title}' {'≠' if neg else '='} '{match}'"))

    if agree and not disagree and not changes and f.confidence < AGREE_CONF:
        # zgoda podnosi pewność, ale nie wyciąga niepewnego pola spod progu przeglądu
        f.confidence = min(AGREE_CONF, c0 + 0.1) if c0 >= OVERRIDE_BELOW else min(c0 + 0.05, OVERRIDE_BELOW - 0.01)
        f.evidence.append(_ev("LLM potwierdza decyzję reguł"))
        changes.append("potwierdzenie")
    return changes


def _is_ancestor(f: DraftField, other: DraftField) -> bool:
    stack = list(f.children)
    while stack:
        x = stack.pop()
        if x is other:
            return True
        stack.extend(x.children)
    return False


def fuse(draft: DraftForm, responses: list[dict[str, Any]]) -> list[str]:
    """Stosuje odpowiedzi LLM do `draft` (w miejscu). Zwraca listę zmian."""
    by_key = {f.key: f for f in all_fields(draft)}
    log: list[str] = []
    done: set[str] = set()
    for resp in responses:
        title = _str(resp.get("form_title"))
        if title and "form_title" not in done:
            done.add("form_title")
            if fold(title) == fold(draft.title):
                if draft.title_confidence < AGREE_CONF:
                    draft.title_confidence = AGREE_CONF
                    draft.title_evidence.append(_ev("LLM potwierdza tytuł formularza"))
            elif draft.title_confidence < OVERRIDE_BELOW and 3 <= len(title) <= 250 and not _BAD_TITLE.search(title):
                draft.title_evidence.append(_ev(f"LLM: tytuł '{title}' zamiast '{draft.title}'"))
                log.append(f"tytuł formularza '{draft.title}'->'{title}'")
                draft.title = title
                draft.title_confidence = LLM_CONF
        items = resp.get("fields")
        if not isinstance(items, list):
            continue
        for raw in items:
            s = normalize(raw)
            if s is None:
                continue
            key = _str(s.get("key"))
            f = by_key.get(key)
            if f is None or key in done:
                continue
            done.add(key)
            log.extend(f"{key}: {c}" for c in fuse_field(f, s, by_key))
    return log
