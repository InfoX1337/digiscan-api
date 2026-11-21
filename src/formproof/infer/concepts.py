"""Katalog pojęć administracyjnych: etykieta z formularza -> pola eUsługi (typ, walidatory, rozwinięcia).

Ogólne reguły językowe (polskie formularze urzędowe), bez odwołań do konkretnych plików.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..types.form import FieldType, Validator
from .lines import fold

Group = str  # person | address | contact | organ | attachment | "" (pozostałe)


@dataclass
class Spec:
    title: str
    type: FieldType = "TEXT_FIELD"
    validation: list[Validator] = field(default_factory=list)
    group: Group = ""
    confidence: float = 0.9
    reason: str = ""
    from_doc: bool = True  # False = dodane z rozwinięcia standardu (bez bezpośredniego śladu w dokumencie)
    show_when: tuple[str, str, bool] | None = None  # (tytuł pola-wyzwalacza w tej samej grupie, wartość, negacja)
    options: list[str] = field(default_factory=list)


def _r(p: str) -> re.Pattern[str]:
    return re.compile(p)


ADDRESS_GENERIC = _r(r"^(adres|adres zamieszkania|adres siedziby|adres do korespondencji|adres zameldowania)\b.*$")
ADDRESS_PARTS: list[tuple[re.Pattern[str], str, list[Validator]]] = [
    (_r(r"kod\w* poczt"), "Kod pocztowy", ["ZIP_CODE"]),
    (_r(r"miejscowo|miasto|^poczta$"), "Miejscowość", []),
    (_r(r"ulic|^ul\b"), "Ulica", []),
    (_r(r"(nr|numer)\s*(domu|budynku)|^nr dom|^nr bud"), "Numer budynku", []),
    (_r(r"(nr|numer)\s*(lokalu|mieszkania)"), "Numer lokalu", []),
    (_r(r"wojewodztw"), "Województwo", []),
    (_r(r"powiat"), "Powiat", []),
    (_r(r"^gmina|^gmin\b"), "Gmina", []),
    (_r(r"^kraj|panstw"), "Kraj", []),
]


def address_set(reason: str, found: set[str]) -> list[Spec]:
    """Standard adresu eUsługi: kraj + pola dla Polski + pola dla adresu zagranicznego (SHOW zależne od kraju)."""

    def s(title: str, val: list[Validator] | None = None, show: tuple[str, str, bool] | None = None) -> Spec:
        known = title in found
        return Spec(
            title=title,
            validation=list(val or []),
            group="address",
            confidence=0.9 if known else 0.62,
            reason="etykieta w dokumencie" if known else reason,
            from_doc=known,
            show_when=show,
        )

    pl = ("Kraj", "Polska", False)
    zagr = ("Kraj", "Polska", True)
    kraj = s("Kraj")
    kraj.type = "SELECT"
    return [
        kraj,
        s("Województwo", show=pl),
        s("Miejscowość", show=pl),
        s("Kod pocztowy", ["ZIP_CODE"], show=pl),
        s("Ulica", show=pl),
        s("Numer budynku"),
        s("Numer lokalu"),
        Spec("Miejscowość (zagranica)", group="address", confidence=0.6, reason=reason, from_doc=False, show_when=zagr),
        Spec(
            "Kod pocztowy (zagranica)", group="address", confidence=0.6, reason=reason, from_doc=False, show_when=zagr
        ),
    ]


# (wzorzec po fold(), tytuł kanoniczny | None = zostaw etykietę, typ, walidatory, grupa)
SIMPLE: list[tuple[re.Pattern[str], str | None, FieldType, list[Validator], Group]] = [
    (_r(r"\bpesel\b"), "Numer PESEL", "TEXT_FIELD", ["PESEL"], "person"),
    (_r(r"\bnip\b"), "NIP", "TEXT_FIELD", ["NIP"], ""),
    (_r(r"\bregon\b"), "REGON", "TEXT_FIELD", ["REGON"], ""),
    (_r(r"\bkrs\b"), "Numer KRS", "TEXT_FIELD", [], ""),
    (_r(r"e-?mail|poczty elektronicznej|adres elektroniczny"), "Adres e-mail", "TEXT_FIELD", ["EMAIL"], "contact"),
    (_r(r"telefon|\btel\b"), "Numer telefonu", "TEXT_FIELD", [], "contact"),
    (_r(r"epuap|skrytk"), "Adres skrytki ePUAP", "TEXT_FIELD", ["EPUAP"], "contact"),
    (_r(r"e-?dorecz"), "Adres do e-Doręczeń", "TEXT_FIELD", ["ADE"], "contact"),
    (_r(r"(seria|numer).*dowod"), "Seria i numer dowodu osobistego", "TEXT_FIELD", ["SERIAL_NUMBER_ID_CARD"], "person"),
    (_r(r"rachunk|konta bank|iban"), None, "TEXT_FIELD", [], ""),
    (_r(r"\bdata\b|dd-mm|\bdnia\b|termin"), None, "DATEPICKER", [], ""),
    (_r(r"kwot|wysokos|liczba|ilosc|powierzchni|\bzl\b|metraz|\bm2\b"), None, "NUMBER", [], ""),
    (_r(r"uzasadnien|opis|uwagi|cel |^cel$|wyjasnien|informacje dodatkowe|tresc"), None, "TEXTAREA", [], ""),
    (_r(r"^nazwisko$"), "Nazwisko", "TEXT_FIELD", [], "person"),
    (_r(r"^imie$|^imiona$"), "Imię", "TEXT_FIELD", [], "person"),
    (_r(r"obreb"), "Obręb", "TEXT_FIELD", [], ""),
    (_r(r"dzialk"), "Numer ewidencyjny działki", "TEXT_FIELD", [], ""),
]

DROP = _r(r"^podpis|czytelny podpis|^\(?podpis")
NAME_PAIR = _r(r"imi\w* i nazwisk|nazwisko i imi")


def _cap(s: str) -> str:
    s = s.strip()
    if s.isupper() and len(s) > 3:
        s = s.lower()
    return s[:1].upper() + s[1:]


def specs_for_label(label: str) -> list[Spec]:
    """Zwraca 0..n pól dla etykiety (0 = pomiń, np. podpis odręczny)."""
    f = fold(label).strip(" .:")
    if not f or DROP.search(f):
        return []
    parts = [p for p in re.split(r"\s*/\s*|\s+lub\s+(?=adres|nr|numer|e-?mail|tel)", f) if p] if "/" in f else [f]
    if len(parts) > 1 and not NAME_PAIR.search(f):
        out: list[Spec] = []
        for p in parts:
            out.extend(specs_for_label(p))
        return out
    if NAME_PAIR.search(f):
        sp = [
            Spec("Imię", group="person", reason="rozdzielono 'imię i nazwisko'"),
            Spec("Nazwisko", group="person", reason="rozdzielono 'imię i nazwisko'"),
        ]
        if "nazwa" in f:
            sp.insert(0, Spec("Nazwa", group="person", confidence=0.7, reason="'nazwa' dla podmiotu niebędącego osobą"))
        return sp
    if ADDRESS_GENERIC.match(f) and not re.search(r"e-?mail|elektron|skrytk", f):
        return address_set("rozwinięto ogólne pole 'adres' wg standardu adresu eUsługi", set())
    for pat, title, typ, val in ((p, t, ty, v) for p, t, ty, v, _ in ADDRESS_PARTS_AS_SIMPLE):
        if pat.search(f):
            return [Spec(title, typ, list(val), group="address", reason="składnik adresu")]
    for pat, title2, typ, val, grp in SIMPLE:
        if pat.search(f):
            return [Spec(title2 or _cap(label), typ, list(val), group=grp, reason=f"typ z etykiety ({typ})")]
    return [Spec(_cap(label), confidence=0.8, reason="etykieta w dokumencie")]


ADDRESS_PARTS_AS_SIMPLE: list[tuple[re.Pattern[str], str, FieldType, list[Validator], Group]] = [
    (p, t, "TEXT_FIELD", v, "address") for p, t, v in ADDRESS_PARTS
]


def address_title(f: str) -> str | None:
    """Tytuł kanoniczny składnika adresu (do scalenia ze standardem) albo None."""
    for p, t, _ in ADDRESS_PARTS:
        if p.search(fold(f)):
            return t
    return None


SECTION_PERSON = _r(
    r"wnioskodaw|dane identyfikac|dane osob|podmiot|zglaszaj|inwestor|wlascicie|najemc|osoba|dane strony"
)
SECTION_PROXY = _r(r"pelnomocni")
SECTION_CONTACT = _r(r"kontakt")
SECTION_ATTACH = _r(r"zalacznik|dokumenty dolacz")
SECTION_SKIP = _r(r"instrukcj|sposob wypelnien|objasnien|pouczeni|adnotacje urzedu|wypelnia urzad|podpis")
SECTION_CONSENT = _r(r"klauzul|rodo|ochron\w* danych|przetwarzani\w* danych|oswiadczen")
CHOICE_HINT = _r(r"postaw\s*[„\"']?x|zaznacz|wybierz|wlasciwe|\bx\b")
MULTI_HINT = _r(r"mozna zaznaczyc (kilka|wiecej)|zaznacz wszystkie|wielokrotn")
CONDITION = _r(r"^(jesli|jezeli|w przypadku)\b")
OPTIONAL = _r(r"nieobowiazkow|nie sa obowiazkowe|nie jest obowiazkow|opcjonaln|fakultatywn")
TITLE_START = _r(
    r"^(wniosek|zgloszenie|deklaracja|oswiadczenie|podanie|formularz|karta|informacja|zawiadomienie|zapotrzebowanie)\b"
)
ORGAN = _r(r"^(urzad|wojt|burmistrz|prezydent|starost|marszal|gmina|starostwo|dyrektor|kierownik|rada)\b")
ADDRESSEE = _r(r"^(adresat|do|organ)\s*:?$")
