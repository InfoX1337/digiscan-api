"""LLM (R3): przebudowa struktury części formularza wypełnianej przez wnioskodawcę.

Model dostaje tekst dokumentu i zwraca sekcje + pola w zwięzłym formacie liniowym. Każda etykieta,
opcja i oświadczenie musi mieć potwierdzenie w tekście dokumentu (dowód = blok źródłowy) – inaczej
jest odrzucana. Zakładki standardu eUsługi (Dane, Kontakt i zgody, Strona końcowa) zostają; LLM
przebudowuje zakładkę „Szczegóły wniosku” i ewentualnie uzupełnia oświadczenia.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from typing import Any, cast

from ..infer import address_fields
from ..infer.concepts import SECTION_PERSON, specs_for_label
from ..types.draft import DraftField, DraftForm, DraftOption, DraftTab, Evidence, iter_draft
from ..types.form import CONTAINER_TYPES, Consent, ConsentSectionConfig, FieldType, Validator
from ..types.source import SourceBlock, SourceDoc
from .fusion import fold

DETAILS_TAB = "Szczegóły wniosku"
CONTACT_TAB = "Kontakt i zgody"
MAX_TEXT_CHARS = 9000
GROUND_MIN = 0.6  # minimalne pokrycie słów etykiety przez blok dokumentu
MIN_FIELDS = 2  # mniej ugruntowanych pól = odpowiedź odrzucona, zostaje wynik reguł

SYSTEM = (
    "Jesteś ekspertem od cyfryzacji polskich formularzy urzędowych do e-usług. Dostajesz tekst formularza "
    "(z pliku albo z OCR – mogą być literówki i szum). Odtwórz strukturę części wypełnianej przez wnioskodawcę: "
    "sekcje i pola w kolejności dokumentu. Zasady: pomiń dane urzędu (pieczęć, nr sprawy, 'wypełnia organ', "
    "nazwa i adres urzędu, numer konta i kwota opłaty), podpis, datę i miejscowość złożenia, klauzulę RODO / "
    "informację o przetwarzaniu danych, przypisy, instrukcje i wersję formularza. Nie wymyślaj pól, których nie "
    "ma w tekście. Etykiety pisz krótko, poprawną polszczyzną, bez kropek i dwukropków, poprawiając literówki OCR, "
    "ale tymi samymi słowami co w dokumencie. Kilka kratek dla jednego pytania ('☐ pies ☐ suka') to jedno pole "
    "RADIO z opcjami. Wykropkowane miejsce pod etykietą (adres, opis) to pole. Każde pole to jedna etykieta "
    "z dokumentu – nie łącz dwóch pól w jedno. Odpowiadaj wyłącznie JSON-em."
)

LINE_FORMAT = (
    "Zwróć w `lines` listę napisów w kolejności dokumentu:\n"
    "'S|Tytuł sekcji' – nowa sekcja (nagłówek z dokumentu, np. 'Dane identyfikacyjne wnioskodawcy');\n"
    "'F|TYP|Etykieta|opcja1;opcja2|W' – pole: W = wymagane, O = opcjonalne; opcje tylko dla RADIO/CHECKBOX/SELECT;\n"
    "'Z|Treść oświadczenia' – oświadczenie wnioskodawcy do zaakceptowania.\n"
    "TYP: TEXT_FIELD (krótki tekst), TEXTAREA (dłuższy opis), NUMBER, DATEPICKER (data), RADIO (jedna z opcji), "
    "CHECKBOX (wiele opcji), SELECT (lista), FILE_UPLOADER (załącznik), ADRES (adres: ulica, nr domu, lokal, "
    "miejscowość, kod – zawsze JEDNO pole ADRES, nie osobne pola składników).\n"
    "W `title` podaj pełny tytuł formularza.\n"
    "Przykład (inny formularz):\n"
    "S|Dane wnioskodawcy\nF|TEXT_FIELD|Imię i nazwisko|W\nF|ADRES|Adres zamieszkania|W\n"
    "S|Przedmiot wniosku\nF|RADIO|Rodzaj zaświadczenia|o zameldowaniu;o niezaleganiu|W\n"
    "F|TEXTAREA|Uzasadnienie|O\nZ|Oświadczam, że dane podane we wniosku są zgodne z prawdą."
)

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"title": {"type": "string"}, "lines": {"type": "array", "items": {"type": "string"}}},
    "required": ["title", "lines"],
}

_TYPE_ALIASES = {
    "TEXT": "TEXT_FIELD",
    "TEXTFIELD": "TEXT_FIELD",
    "TEXT_AREA": "TEXTAREA",
    "DATE": "DATEPICKER",
    "DATA": "DATEPICKER",
    "FILE": "FILE_UPLOADER",
    "ZALACZNIK": "FILE_UPLOADER",
    "ADDRESS": "ADRES",
    "LICZBA": "NUMBER",
}
_OK_TYPES = {"TEXT_FIELD", "TEXTAREA", "NUMBER", "DATEPICKER", "RADIO", "CHECKBOX", "SELECT", "FILE_UPLOADER", "ADRES"}
_CHOICE = {"RADIO", "CHECKBOX", "SELECT"}
_OTHER_ADDRESS = re.compile(
    r"\bmiejsc(e|a|u)\b|utrzym|korespond|\binne[jg]?\b|siedzib|dzialk|nieruchom|zakład|zaklad|prowadzen"
)
_STOP = {"i", "w", "z", "o", "na", "do", "od", "lub", "oraz", "the", "nr", "jego", "jej", "przypadku"}


@dataclass
class Prompt:
    system: str
    user: str
    schema: dict[str, Any]


@dataclass
class Outcome:
    draft: DraftForm
    changes: list[str] = field(default_factory=list)
    created: set[str] = field(default_factory=set)  # klucze pól utworzonych przez LLM
    applied: bool = False


def _words(s: str) -> list[str]:
    return [w for w in fold(s).split() if w not in _STOP and len(w) > 1]


_RODO = re.compile(
    r"^(informacj\w* (dotyczac\w* |o )?przetwarzani|klauzul\w* (informacyjn|rodo)|obowiazek informacyjny|"
    r"informacja (o|dotyczaca) ochron)"
)


def _row_key(b: SourceBlock) -> tuple[int, float, float] | None:
    return (b.page, b.bbox.y + b.bbox.h / 2, b.bbox.h) if b.bbox else None


def doc_lines(doc: SourceDoc, limit: int = MAX_TEXT_CHARS) -> str:
    """Tekst dla LLM: bloki z tego samego wiersza łączone ' | ' (etykieta i kratki obok), bez klauzuli RODO."""
    rows: list[list[SourceBlock]] = []
    for b in doc.blocks:
        k = _row_key(b)
        if rows and k is not None:
            p = _row_key(rows[-1][-1])
            if p is not None and p[0] == k[0] and abs(p[1] - k[1]) < 0.5 * max(p[2], k[2], 1.0):
                rows[-1].append(b)
                continue
        rows.append([b])
    parts: list[str] = []
    size = 0
    for n, row in enumerate(rows):
        cells: list[str] = []
        for b in sorted(row, key=lambda x: x.bbox.x if x.bbox else 0.0):
            t = " ".join(b.text.split())
            if b.kind == "checkbox":
                t = "☐ " + t
            elif b.kind == "line":
                t = "……"
            if t:
                cells.append(t)
        t = " | ".join(cells)
        if not t:
            continue
        if n > 0.4 * len(rows) and _RODO.match(fold(t)):
            parts.append("(dalej klauzula informacyjna RODO – pominięta)")
            break
        if size + len(t) + 1 > limit:
            parts.append("…(obcięto)")
            break
        parts.append(t)
        size += len(t) + 1
    return "\n".join(parts)


def _other_titles(draft: DraftForm) -> list[str]:
    return [
        f.title
        for t in draft.tabs
        if t.title != DETAILS_TAB and t.type == "MAIN"
        for f in iter_draft(t.fields)
        if f.type not in CONTAINER_TYPES and f.title
    ]


def build_prompt(doc: SourceDoc, draft: DraftForm) -> Prompt:
    others = sorted(set(_other_titles(draft)))
    user = (
        f"TEKST FORMULARZA:\n{doc_lines(doc)}\n\n"
        + (
            "Pola, które e-usługa ma już w standardowych sekcjach (nie musisz ich powtarzać): "
            + ", ".join(others[:40])
            + "\n\n"
            if others
            else ""
        )
        + LINE_FORMAT
    )
    return Prompt(system=SYSTEM, user=user, schema=SCHEMA)


# ---------- ugruntowanie w dokumencie ----------


class Grounder:
    def __init__(self, doc: SourceDoc) -> None:
        self.blocks = [b for b in doc.blocks if b.text.strip()]
        self.words = [set(_words(b.text)) for b in self.blocks]
        self.vocab = set().union(*self.words) if self.words else set()

    @staticmethod
    def _hit(w: str, ws: set[str]) -> bool:
        if w in ws:
            return True
        # literówki OCR / odmiana: 'psow' ~ 'psa', 'oznakowania' ~ 'oznakowanie'
        return any(
            len(w) >= 4
            and len(x) >= 4
            and (x.startswith(w[:4]) and difflib.SequenceMatcher(None, w, x).ratio() >= 0.75)
            for x in ws
        )

    def locate(self, label: str) -> tuple[float, list[SourceBlock]]:
        """Najlepszy blok (lub 2 sąsiednie) pokrywający słowa etykiety. Zwraca (pokrycie 0..1, bloki)."""
        ws = _words(label)
        if not ws:
            return 0.0, []
        single: tuple[float, list[SourceBlock]] = (0.0, [])
        pair: tuple[float, list[SourceBlock]] = (0.0, [])
        for i, bw in enumerate(self.words):
            score = sum(self._hit(w, bw) for w in ws) / len(ws)
            if score > single[0]:
                single = (score, [self.blocks[i]])
            if i + 1 < len(self.words) and bw and self.words[i + 1]:
                s2 = sum(self._hit(w, bw | self.words[i + 1]) for w in ws) / len(ws)
                if s2 > pair[0]:
                    pair = (s2, [self.blocks[i], self.blocks[i + 1]])
        # etykieta rozbita na 2 sąsiednie bloki – tylko gdy wyraźnie lepiej niż pojedynczy blok
        return pair if pair[0] > single[0] + 0.2 else single

    def known(self, text: str) -> bool:
        ws = _words(text)
        return bool(ws) and sum(self._hit(w, self.vocab) for w in ws) / len(ws) >= GROUND_MIN


# ---------- parsowanie ----------


@dataclass
class _F:
    type: str
    label: str
    options: list[str]
    required: bool
    hint: str = ""


def _clean_label(s: str) -> str:
    s = re.sub(r"\s+", " ", s).strip(" .:;*-–|\"'")
    s = re.sub(r"\*+", "", s).strip()
    return s[:1].upper() + s[1:] if s else s


def parse(resp: dict[str, Any]) -> tuple[str, list[tuple[str, list[_F]]], list[str]]:
    t = resp.get("title")
    title = t if isinstance(t, str) else ""
    sections: list[tuple[str, list[_F]]] = []
    consents: list[str] = []
    raw = resp.get("lines")
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, str) or "|" not in item:
            continue
        parts = [p.strip() for p in item.strip().strip("'\"").split("|")]
        tag = parts[0].upper()
        if tag == "S" and len(parts) >= 2 and parts[1]:
            sections.append((_clean_label(parts[1]), []))
        elif tag == "Z" and len(parts) >= 2 and parts[1]:
            consents.append(re.sub(r"^\d+[.)]\s*", "", "|".join(parts[1:]).strip()))
        elif tag == "F" and len(parts) >= 3:
            typ = parts[1].upper().replace(" ", "_")
            typ = _TYPE_ALIASES.get(typ, typ)
            if typ not in _OK_TYPES:
                typ = "TEXT_FIELD"
            label = _clean_label(parts[2])
            rest = parts[3:]
            req = True
            if rest and rest[-1].upper() in ("W", "O"):
                req = rest[-1].upper() == "W"
                rest = rest[:-1]
            opts = [_clean_label(o) for o in ";".join(rest).split(";") if _clean_label(o)] if typ in _CHOICE else []
            if typ in _CHOICE and not opts and ";" in label:
                # 'Sposób oznakowania mikroprocesor;tatuaż;brak' – opcje sklejone z etykietą
                head, *more = label.split(";")
                words = head.split()
                if len(words) >= 2:
                    label, opts = (
                        _clean_label(" ".join(words[:-1])),
                        [_clean_label(words[-1]), *map(_clean_label, more)],
                    )
            hint = ""
            m = re.match(r"^(.{2,}?)\s*\((.+)\)\s*$", label)
            if m:  # 'Pochodzenie psa (metryka, numer rodowodu…)' -> etykieta + podpowiedź
                label, hint = _clean_label(m.group(1)), m.group(2).strip()
            if not label:
                continue
            if not sections:
                sections.append(("", []))
            sections[-1][1].append(_F(typ, label, opts, req, hint))
    return title.strip(), [(t, _merge_address(fs)) for t, fs in sections], consents


_ADDR_PART = re.compile(
    r"^(ulica|ul|nr domu|numer domu|nr budynku|numer budynku|nr lokalu|numer lokalu|nr mieszkania|miejscowosc|"
    r"kod pocztowy|kod|poczta|gmina|powiat|wojewodztwo|kraj)$"
)


def _merge_address(fields: list[_F]) -> list[_F]:
    """Kolejne składniki adresu (Ulica, Nr domu, Miejscowość…) -> jedno pole ADRES (standard adresu eUsługi)."""
    out: list[_F] = []
    run: list[_F] = []

    def close() -> None:
        if len(run) >= 2:
            out.append(_F("ADRES", "Adres", [], any(f.required for f in run)))
        else:
            out.extend(f if f.type != "ADRES" else _F("TEXT_FIELD", f.label, [], f.required) for f in run)
        run.clear()

    for f in fields:
        if _ADDR_PART.match(fold(f.label)):
            run.append(f)
            continue
        close()
        out.append(f)
    close()
    return out


_PRINTED = re.compile(r"\d[\d ]{9,}|\d+(,\d+)?\s*zl\b")


def _printed(label: str, blocks: list[SourceBlock]) -> bool:
    """Etykieta z nadrukowaną wartością ('Numer konta: 12 1223…', 'Opłata skarbowa – 82 zł') to nie pole."""
    text = fold(" ".join(b.text for b in blocks))
    lab = fold(label)
    tail = text.split(lab, 1)[1] if lab and lab in text else text
    return bool(_PRINTED.search(tail))


# ---------- budowa ----------


class _Keys:
    def __init__(self, draft: DraftForm) -> None:
        nums = [int(m.group(1)) for t in draft.tabs for f in iter_draft(t.fields) if (m := re.match(r"f(\d+)$", f.key))]
        self.n = max(nums, default=0)

    def __call__(self) -> str:
        self.n += 1
        return f"f{self.n}"


def _ev(blocks: list[SourceBlock], reason: str) -> list[Evidence]:
    return [Evidence(block_ids=[b.id for b in blocks], by="llm", reason=reason)]


def _covered(label: str, others: list[str]) -> bool:
    """Pole już jest w standardowych sekcjach (Dane / Kontakt): 'Imię i nazwisko' gdy są 'Imię' i 'Nazwisko'."""
    fl = fold(label)
    of = [fold(o) for o in others]
    if fl in of:
        return True
    ws = _words(label)
    if not ws:
        return False
    return all(
        any(w in o.split() or (len(w) > 4 and any(x.startswith(w[:5]) for x in o.split())) for o in of) for w in ws
    )


def _same(a: str, b: str) -> bool:
    """To samo po usunięciu spacji ('posiadanymsie' ~ 'posiadanym psie')."""
    x, y = fold(a).replace(" ", ""), fold(b).replace(" ", "")
    return difflib.SequenceMatcher(None, x, y).ratio() >= 0.9


def _sentence_case(s: str) -> str:
    s = re.sub(r"^[A-Z]\s*\|\s*", "", s)  # 'A | DANE …' – litera sekcji z tabeli
    return s[:1].upper() + s[1:].lower() if s.isupper() else s


def _doc_label(text: str) -> str:
    """Etykieta tak, jak stoi w dokumencie: tekst przed nawiasem / dwukropkiem."""
    t = re.split(r"[(:]", text, maxsplit=1)[0]
    return _clean_label(re.sub(r"[☐□…_.]{2,}.*$", "", t))


def _match_old(label: str, old: list[DraftField]) -> DraftField | None:
    fl = fold(label)
    best, score = None, 0.0
    for f in old:
        r = difflib.SequenceMatcher(None, fl, fold(f.title)).ratio()
        if r > score:
            best, score = f, r
    return best if score >= 0.85 else None


def apply(doc: SourceDoc, draft: DraftForm, resp: dict[str, Any]) -> Outcome:
    """Stosuje odpowiedź LLM do kopii `draft`. Nie rzuca – przy słabej odpowiedzi zwraca draft bez zmian."""
    out = draft.model_copy(deep=True)
    res = Outcome(draft=out)
    title, sections, consents = parse(resp)
    g = Grounder(doc)
    key = _Keys(out)
    others = _other_titles(out)
    has_address_elsewhere = any(fold(t) in ("ulica", "miejscowosc", "kod pocztowy") for t in others)
    details = next((t for t in out.tabs if t.title == DETAILS_TAB), None)
    old = [f for f in iter_draft(details.fields) if f.type not in CONTAINER_TYPES] if details else []

    new_sections: list[DraftField] = []
    applicant: list[DraftField] = []  # sekcje danych wnioskodawcy -> zakładka „Dane”
    n_fields = 0

    def flush(stitle: str, children: list[DraftField], free_title: bool = False, person: bool = False) -> None:
        if not children:
            return
        sscore, sblocks = g.locate(stitle) if stitle else (0.0, [])
        if (
            not free_title
            and sscore >= 0.5
            and len(sblocks) == 1
            and (dl := _doc_label(sblocks[0].text))
            and len(dl) <= 90
        ):
            dw, tw = set(_words(dl)), set(_words(stitle))
            if sscore < 1 or (
                fold(dl) != fold(stitle)
                and (
                    all(Grounder._hit(w, tw) for w in dw) and all(Grounder._hit(w, dw) for w in tw) or _same(dl, stitle)
                )
            ):
                stitle, sscore = _sentence_case(dl), 1.0  # nagłówek w brzmieniu z dokumentu (literówka LLM)
        ok = bool(sblocks) and sscore >= GROUND_MIN
        sec = DraftField(
            key=key(),
            type="SECTION",
            title=(stitle if ok or free_title else "") or "Dane wniosku",
            children=list(children),
            confidence=round(min(0.9, sum(c.confidence for c in children) / len(children)), 2),
            evidence=_ev(sblocks, "LLM: nagłówek sekcji w dokumencie")
            if ok
            else [Evidence(by="llm", reason="LLM: grupa pól")],
        )
        res.created.add(sec.key)
        (applicant if person else new_sections).append(sec)
        children.clear()

    dane = next((t for t in out.tabs if t.title == "Dane"), None)
    for stitle, fields in sections:
        children: list[DraftField] = []
        person = dane is not None and bool(SECTION_PERSON.search(fold(stitle))) and "pelnomocn" not in fold(stitle)
        for f in fields:
            score, blocks = g.locate(f.label)
            if f.type == "ADRES":
                s2, b2 = g.locate("Ulica Miejscowość Kod pocztowy")
                if score < GROUND_MIN and s2 >= GROUND_MIN:
                    score, blocks = s2, b2
            elif 0.5 <= score < 1 and len(blocks) == 1:
                dl = _doc_label(blocks[0].text)
                dw, lw = _words(dl), set(_words(f.label))
                if dw and len(dl) <= 80 and all(Grounder._hit(w, lw) for w in dw):
                    res.changes.append(f"etykieta '{f.label}' -> '{dl}' (brzmienie z dokumentu)")
                    f.label, score = dl, max(score, 0.9)
            if len(f.label) > 90:
                res.changes.append(f"odrzucono '{f.label[:40]}…' (zdanie, nie etykieta)")
                continue
            if f.type != "ADRES" and _covered(f.label, others):
                res.changes.append(f"pominięto '{f.label}' (jest w sekcjach standardowych)")
                continue
            if score < GROUND_MIN:
                res.changes.append(f"odrzucono '{f.label}' (brak w dokumencie, pokrycie {score:.2f})")
                continue
            if f.type != "ADRES" and _printed(f.label, blocks):
                res.changes.append(f"odrzucono '{f.label}' (nadrukowana wartość, nie pole)")
                continue
            conf = round(min(0.9, 0.55 + 0.35 * score), 2)
            reason = "LLM: pole odczytane ze struktury dokumentu"
            if f.type == "ADRES":
                ctx = fold(stitle + " " + f.label)
                if has_address_elsewhere and not _OTHER_ADDRESS.search(ctx):
                    res.changes.append(f"pominięto adres '{f.label}' (adres wnioskodawcy jest w sekcji Dane)")
                    continue
                flush(stitle, children, person=person)  # adres = osobna sekcja ze standardem adresu eUsługi
                addr = address_fields(key, optional=not f.required)
                for a in addr:
                    a.confidence = min(a.confidence, conf)
                    a.evidence = [
                        *_ev(blocks, f"LLM: adres '{f.label}' – składnik wg standardu adresu eUsługi"),
                        *a.evidence,
                    ]
                    res.created.add(a.key)
                generic = fold(f.label) in ("adres", "adres zamieszkania")
                atitle = "Adres zamieszkania" if person and generic else f.label
                if generic and not person:
                    atitle = f"Adres – {stitle.lower()}" if stitle else "Adres"
                flush(atitle, addr, free_title=True, person=person)
                n_fields += 1
                continue
            typ = f.type
            opts = [o for o in f.options if g.known(o)] if typ in _CHOICE else []
            if typ in _CHOICE and len(opts) < 2:
                typ = "TEXT_FIELD"
                opts = []
            df = DraftField(
                key=key(),
                type=cast(FieldType, typ),
                title=f.label[:200],
                options=[DraftOption(name=o) for o in opts],
                validation=["REQUIRED"] if f.required else [],
                tooltip_message=f.hint[:300] or None,
                confidence=conf,
                evidence=_ev(blocks, reason),
            )
            prev = _match_old(f.label, old)
            hints = specs_for_label(f.label)
            vals: list[Validator] = [
                v for v in (prev.validation if prev else (hints[0].validation if hints else [])) if v != "REQUIRED"
            ]
            if typ in ("TEXT_FIELD", "NUMBER") and vals:
                df.validation = [*df.validation, *vals[:1]]
            if prev is not None:
                df.dictionary_name = prev.dictionary_name if typ in ("SELECT", "TEXT_FIELD") else None
                if prev.dictionary_name and typ == "TEXT_FIELD":
                    df.type = "SELECT"
                df.evidence = [*prev.evidence, *df.evidence]
                if prev.type == df.type:
                    df.confidence = max(df.confidence, min(0.9, prev.confidence + 0.1))
                    df.evidence.append(Evidence(by="llm", reason="LLM potwierdza pole wykryte regułami"))
            res.created.add(df.key)
            children.append(df)
            n_fields += 1
        flush(stitle, children, person=person)

    n_fields += _backfill(old, new_sections, applicant, others, g, res)
    if n_fields < MIN_FIELDS:
        res.changes.append(f"odpowiedź LLM odrzucona: {n_fields} ugruntowanych pól")
        return Outcome(draft=draft, changes=res.changes)

    # zakładka szczegółów: sekcje LLM zamiast wyniku reguł (bloki tekstu informacyjnego reguł zostają na górze)
    kept_info = [
        f
        for f in (details.fields if details else [])
        if f.type == "SECTION" and all(c.type == "INFO_SECTION" for c in f.children)
    ]
    if details is None:
        details = DraftTab(title=DETAILS_TAB, confidence=0.75)
        idx = next((i for i, t in enumerate(out.tabs) if t.title == CONTACT_TAB or t.type == "FINISH"), len(out.tabs))
        out.tabs.insert(idx, details)
    res.changes.append(
        f"zakładka '{DETAILS_TAB}': {len(old)} pól reguł -> {n_fields} pól LLM w {len(new_sections)} sekcjach"
    )
    details.fields = [*kept_info, *new_sections]
    details.confidence = 0.8
    if dane is not None and applicant:
        _to_applicant(dane, applicant, res)

    _apply_consents(out, g, consents, key, res)
    _apply_title(out, g, title, res)
    res.applied = True
    return res


def _to_applicant(dane: DraftTab, sections: list[DraftField], res: Outcome) -> None:
    """Dane wnioskodawcy z dokumentu: pola dopisane do sekcji osoby (Imię, Nazwisko), adres jako osobna sekcja."""
    person = next(
        (s for s in dane.fields if s.type == "SECTION" and any(c.title in ("Imię", "Nazwisko") for c in s.children)),
        None,
    )
    at = dane.fields.index(person) + 1 if person else len(dane.fields)
    for sec in sections:
        is_addr = any(c.dictionary_name == "Kraje" for c in sec.children)
        if person is not None and not is_addr:
            person.children.extend(sec.children)
            res.changes.append(f"dane wnioskodawcy: {len(sec.children)} pól do sekcji '{person.title}'")
            continue
        dane.fields.insert(at, sec)
        at += 1
        res.changes.append(f"dane wnioskodawcy: sekcja '{sec.title}' w zakładce Dane")


BACKFILL_MIN = 0.85  # pole reguł o tak wysokiej pewności zostaje, nawet gdy LLM je pominął


def _backfill(
    old: list[DraftField],
    sections: list[DraftField],
    applicant: list[DraftField],
    others: list[str],
    g: Grounder,
    res: Outcome,
) -> int:
    """Pewne pola reguł, których LLM nie zwrócił, wracają do sekcji poprzedzającej je w dokumencie."""
    if not sections:
        return 0
    order = {b.id: i for i, b in enumerate(g.blocks)}

    def pos(f: DraftField) -> int:
        ids = [order[i] for e in f.evidence for i in e.block_ids if i in order]
        return min(ids) if ids else -1

    have = [fold(c.title) for s in [*sections, *applicant] for c in iter_draft(s.children)]
    has_addr = any(c.dictionary_name == "Kraje" for s in [*sections, *applicant] for c in s.children)
    starts = [
        (pos(s) if pos(s) >= 0 else min((pos(c) for c in s.children if pos(c) >= 0), default=-1), s) for s in sections
    ]
    n = 0
    for f in old:
        if f.confidence < BACKFILL_MIN or f.type in ("TEXT_BLOCK", "INFO_SECTION", "CONSENT_SECTION") or not f.title:
            continue
        p = pos(f)
        ft = fold(f.title)
        if has_addr and _ADDR_PART.match(ft):
            continue  # składnik adresu – jest w sekcji adresu (standard eUsługi)
        if (
            p < 0
            or _covered(f.title, others)
            or any(ft == h or difflib.SequenceMatcher(None, ft, h).ratio() >= 0.7 or ft in h or h in ft for h in have)
        ):
            continue
        target = max((x for x in starts if 0 <= x[0] <= p), key=lambda x: x[0], default=starts[0])[1]
        f.evidence.append(
            Evidence(by="llm", reason="pole reguł o wysokiej pewności zachowane mimo pominięcia przez LLM")
        )
        target.children.append(f)
        have.append(ft)
        res.changes.append(f"zachowano pole reguł '{f.title}'")
        n += 1
    return n


def _apply_consents(out: DraftForm, g: Grounder, consents: list[str], key: _Keys, res: Outcome) -> None:
    grounded: list[tuple[str, list[SourceBlock]]] = []
    for c in consents:
        score, blocks = g.locate(c)
        if score >= 0.7 and 10 <= len(c) <= 600:
            grounded.append((c.rstrip(), blocks))
    if not grounded:
        return
    existing = [f for t in out.tabs for f in iter_draft(t.fields) if f.type == "CONSENT_SECTION"]
    items = [Consent(description=c) for c, _ in grounded]
    blocks = [b for _, bs in grounded for b in bs]
    first = fold(grounded[0][0])[:40]
    target = next((f for f in existing if first and first in fold(f.description or "")), None)
    if target is not None and target.consent_section_config is not None:
        rodo = [c for c in target.consent_section_config.consents if "przetwarzani" in fold(c.description)]
        target.consent_section_config.consents = [*items, *rodo]
        target.evidence.extend(_ev(blocks, "LLM: oświadczenia wnioskodawcy jako osobne zgody"))
        res.changes.append(f"oświadczenia: {len(items)} zgód")
        return
    consent = DraftField(
        key=key(),
        type="CONSENT_SECTION",
        title="",
        consent_section_config=ConsentSectionConfig(consents=items, required=True),
        validation=["REQUIRED"],
        confidence=0.75,
        evidence=_ev(blocks, "LLM: oświadczenia wnioskodawcy w dokumencie"),
    )
    sec = DraftField(
        key=key(),
        type="SECTION",
        title="Oświadczenia",
        children=[consent],
        confidence=0.75,
        evidence=list(consent.evidence),
    )
    res.created.update({consent.key, sec.key})
    tab = next((t for t in out.tabs if t.title == CONTACT_TAB), None)
    if tab is None:
        tab = DraftTab(title=CONTACT_TAB, confidence=0.75)
        idx = next((i for i, t in enumerate(out.tabs) if t.type == "FINISH"), len(out.tabs))
        out.tabs.insert(idx, tab)
    tab.fields.append(sec)
    res.changes.append(f"oświadczenia: nowa sekcja, {len(items)} zgód")


def _apply_title(out: DraftForm, g: Grounder, title: str, res: Outcome) -> None:
    title = _clean_label(title)
    if not title or len(title) > 250 or fold(title) == fold(out.title):
        return
    score, blocks = g.locate(title)
    # dłuższy tytuł z dokumentu (np. zawinięty na 2 linie) zastępuje skrócony wynik reguł
    extends = fold(title).startswith(fold(out.title)) and len(title) > len(out.title)
    if not extends and score < 0.85 or extends and (score < 0.7 or not g.known(title[len(out.title) :])):
        return
    if out.title_confidence < 0.6 or extends:
        res.changes.append(f"tytuł '{out.title}' -> '{title}'")
        out.title = title
        out.title_confidence = max(out.title_confidence, 0.8)
        out.title_evidence = [*out.title_evidence, *_ev(blocks, "LLM: pełny tytuł z dokumentu")]
