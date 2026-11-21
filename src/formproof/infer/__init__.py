"""INFER (I1): SourceDoc -> DraftForm. Heurystyki układu + katalog pojęć; każde pole z confidence i dowodem."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..types.draft import DraftField, DraftForm, DraftOption, DraftTab, Evidence, ShowWhen
from ..types.form import Consent, ConsentSectionConfig, Validator
from ..types.source import SourceDoc
from . import concepts as C
from .concepts import Spec
from .lines import FOOTNOTE_MARK, PAREN_HINT, PLACEHOLDER, Line, clean, fold, hint_text, median_font, to_lines

SUBMISSION_META = {"data", "miejscowosc i data", "miejscowosc, data", "data zlozenia wniosku", "data wypelnienia"}
SUBMISSION_PLACE_DATE = re.compile(r"^[\w .-]{2,40},?\s+(dnia|dn\.?)$")  # 'Młynary, dnia ……'
HEADING_NUM = re.compile(r"^(\d{1,2}(?:\.\d{1,2})*)\.?\s+(\S.*)$")
INLINE_FN = re.compile(r"(?:(?<=[^\W\d_])|(?<=\)))(\d)\)(?=\s|$|[._…])")
PAGE_NO = re.compile(r"^(strona|str\.)\s*\d+(\s*(/|z)\s*\d+)?$|^\d+\s*/\s*\d+$|^-?\s*\d+\s*-?$")


@dataclass
class Item:
    spec: Spec
    lines: list[Line]
    optional: bool = False


@dataclass
class Choice:
    title: str
    lines: list[Line]
    options: list[tuple[str, Line]] = field(default_factory=list)
    multi: bool = False


@dataclass
class Section:
    title: str
    lines: list[Line] = field(default_factory=list)
    entries: list[Item | Choice] = field(default_factory=list)
    kind: str = ""  # skip | consent | attach | proxy | person | contact | organ
    choice_mode: bool = False
    optional: bool = False
    pending_cond: tuple[Choice, str] | None = None
    conds: dict[int, tuple[Choice, str]] = field(default_factory=dict)  # id(entry) -> warunek
    texts: list[Line] = field(default_factory=list)
    level: int = 1
    list_choice: Choice | None = None  # 'Proszę o …:' + wyliczenie małą literą -> opcje


class _Keys:
    def __init__(self) -> None:
        self.n = 0

    def __call__(self) -> str:
        self.n += 1
        return f"f{self.n}"


def _ev(lines: list[Line], reason: str, by: str = "rules") -> list[Evidence]:
    ids = [i for ln in lines for i in ln.block_ids]
    return [Evidence(block_ids=ids, by=by, reason=reason)]  # type: ignore[arg-type]


def _sentence(s: str) -> str:
    s = re.sub(r"\s+", " ", s).strip(" :")
    if s.isupper():
        s = s.lower()
    return s[:1].upper() + s[1:]


def _is_heading(ln: Line, mf: float) -> tuple[int, str] | None:
    t = clean(re.sub(r"\(.*$", "", ln.text)) or clean(ln.text)
    if not t or len(t) > 90 or t.endswith((".", ",")) and not HEADING_NUM.match(t):
        return None
    m = HEADING_NUM.match(t)
    if m and not t.endswith(".") and len(m.group(2)) > 2 and not m.group(2)[0].isdigit():
        return m.group(1).count(".") + 1, m.group(2)
    if ln.heading:
        return ln.heading, t
    if ln.kind == "cell" or ln.has_placeholder:
        return None
    if ln.bold and len(t) < 70:
        return 1, t
    if t.isupper() and 3 < len(t) < 70 and len(t.split()) <= 8 and not C.TITLE_START.match(fold(t)):
        return 1, t
    if t.endswith(":") is False and ln.text.strip().endswith(":") and len(t.split()) <= 4 and (ln.font or mf) >= mf:
        return 1, t
    return None


def _title(lines: list[Line], doc: SourceDoc, mf: float) -> tuple[str, float, list[Line]]:
    first_pages = [ln for ln in lines if ln.page <= 2]
    cands = [ln for ln in first_pages if C.TITLE_START.match(fold(clean(ln.text))) and len(clean(ln.text)) < 160]
    if cands:
        best = max(cands, key=lambda ln: ((ln.font or mf), ln.text.isupper(), -lines.index(ln)))
        used = [best]
        t = clean(best.text)
        i = lines.index(best)
        if best.text.isupper() and i + 1 < len(lines):
            nxt = lines[i + 1]
            if nxt.text.isupper() and nxt.page == best.page and not HEADING_NUM.match(nxt.text) and len(nxt.text) < 90:
                t += " " + clean(nxt.text)
                used.append(nxt)
        # 'WNIOSEK' / 'o' / 'wynajęcie świetlicy' – dokończenie tytułu z kolejnych linii pisanych małą literą
        j = i + len(used)
        while len(t.split()) <= 3 and j < len(lines) and j - i <= 3:
            nxt = lines[j]
            nt = clean(nxt.text).replace("*", "").strip()
            if len(nt) <= 1 and not nt.isalnum():  # szum OCR ('°' zamiast 'o')
                j += 1
                continue
            if not nt or nxt.has_placeholder or nxt.page != best.page or not nt[:1].islower() or len(t + nt) > 160:
                break
            t = (_sentence(t) if t.isupper() else t) + " " + nt
            used.append(nxt)
            j += 1
        return _sentence(t)[:255], 0.9, used
    stem = doc.filename.rsplit(".", 1)[0]
    return _sentence(re.sub(r"^\d+[.)]\s*", "", stem))[:255], 0.4, []


def _organ(lines: list[Line]) -> tuple[str, list[Line]] | None:
    """Organ (adresat wniosku): po 'Adresat:' albo nazwa urzędu w górnej części 1. strony."""
    for i, ln in enumerate(lines[:40]):
        if ln.page != 1:
            break
        if C.ADDRESSEE.match(fold(clean(ln.text))):
            col = [
                x
                for x in lines[i + 1 : i + 12]
                if x.page == 1
                and abs(x.x - ln.x) < 40
                and x.y - ln.y < 120
                and clean(x.text)
                and not x.has_placeholder
                and not PAREN_HINT.match(x.text.strip())
            ]
            if col:
                return clean(col[0].text), [ln, *col]
    for ln in lines[:15]:
        if ln.page == 1 and C.ORGAN.match(fold(clean(ln.text))) and len(clean(ln.text)) < 80:
            # adres urzędu pod nazwą ('Płoskinia 8', '14-526 Płoskinia') – nadruk, nie pola
            k = lines.index(ln)
            # z układem: linie adresu w tej samej kolumnie mogą przeplatać się z polami obok (do 6 linii niżej)
            window = lines[k + 1 : k + 7] if ln.bbox else lines[k + 1 : k + 3]
            addr = [
                x
                for x in window
                if x.page == 1
                and not x.has_placeholder
                and len(clean(x.text)) < 50
                and re.search(r"\d", x.text)
                and not PAREN_HINT.match(x.text.strip())
                and (not x.bbox or not ln.bbox or (abs(x.x - ln.x) < 60 and 0 <= x.y - ln.y < 60))
            ][:2]
            return clean(ln.text), [ln, *addr]
    return None


def _starts_list(ln: Line, lines: list[Line], i: int) -> bool:
    """'…:' a pod nim ≥2 pozycje pisane małą literą bez miejsca do wpisania (dokończenia zdania) = wyliczenie opcji."""
    if not ln.text.rstrip(" *").endswith(":"):
        return False
    nxt = [x for x in lines[i : i + 3] if not x.consumed]
    return len(nxt) >= 2 and all(
        clean(x.text)[:1].islower() and not x.has_placeholder and x.kind != "checkbox" and len(clean(x.text)) < 200
        for x in nxt[:2]
    )


def _labels_from_line(ln: Line) -> list[str]:
    """Etykiety pól z linii z miejscami do wpisania ('w miejscowości …… przy ulicy ……')."""
    segs = PLACEHOLDER.split(ln.text)
    out = []
    for i, raw in enumerate(segs):
        s = clean(raw)
        if not s or (i == len(segs) - 1 and len(segs) > 1):  # tekst po ostatnim miejscu do wpisania
            continue
        out.append(re.sub(r"^(w|we|przy|z|o|na|do|od|i)\s+", "", s, flags=re.I))
    if len(segs) == 1 and "input" in ln.tags and clean(ln.text):
        out.append(clean(ln.text))
    return [o for o in out if len(o) > 1]


def infer(doc: SourceDoc) -> DraftForm:
    lines = [ln for ln in to_lines(doc) if ln.text.strip() or ln.kind == "line"]
    mf = median_font(lines)
    key = _Keys()
    title, tconf, tlines = _title(lines, doc, mf)
    for ln in tlines:
        ln.consumed = True

    # przypisy: definicje "1) Dane nieobowiązkowe." na dole strony i odsyłacze "… 1)" przy etykietach
    heights = {pg.page: pg.height for pg in doc.pages if pg.height}
    optional_marks: set[str] = set()
    for ln in lines:
        m = re.match(r"^(\d{1,2})\s?\)\s*(.+)$", ln.text.strip())
        bottom = ln.bbox is not None and ln.page in heights and ln.y > 0.75 * heights[ln.page]
        if m and C.OPTIONAL.search(fold(m.group(2))):
            optional_marks.add(m.group(1))
            ln.consumed = True
        elif m and bottom or re.match(r"^\d{1,2}$", ln.text.strip()) and ln.font and ln.font < 0.75 * mf:
            ln.consumed = True
        else:
            fm = re.search(r"\s(\d{1,2})\)\s*$", ln.text)
            if fm and len(ln.text.strip()) > 3:
                ln.tags.add("fn" + fm.group(1))
                ln.text = ln.text[: fm.start()]
            # odsyłacz przyklejony do słowa/nawiasu: 'przy ulicy1) ____', '(nr telefonu)1)'
            for mk in INLINE_FN.findall(ln.text):
                ln.tags.add("fn" + mk)
            ln.text = INLINE_FN.sub("", ln.text)

    organ = _organ(lines)
    if organ:
        for ln in organ[1]:
            ln.consumed = True

    sections: list[Section] = []
    cur = Section(title="Dane wniosku", kind="")
    sections.append(cur)
    last_item: Item | None = None

    def new_section(t: str, lvl: int, ln: Line) -> Section:
        f = fold(t)
        kind = ""
        if C.SECTION_SKIP.search(f):
            kind = "skip"
        elif C.SECTION_CONSENT.search(f):
            kind = "consent"
        elif C.SECTION_ATTACH.search(f):
            kind = "attach"
        elif C.SECTION_PROXY.search(f):
            kind = "proxy"
        elif C.SECTION_CONTACT.search(f):
            kind = "contact"
        elif C.SECTION_PERSON.search(f):
            kind = "person"
        s = Section(title=_sentence(re.sub(r"\(.*$", "", t)) or _sentence(t), lines=[ln], kind=kind, level=lvl)
        s.choice_mode = bool(C.CHOICE_HINT.search(f)) or kind == "attach"
        s.optional = bool(C.OPTIONAL.search(f))
        # sekcja-dziecko dziedziczy rodzaj rodzica, gdy sama go nie ma (np. 2.1 Dane identyfikacyjne)
        parent = next((p for p in reversed(sections) if p.level < lvl), None)
        if parent and not kind and parent.kind in ("person", "proxy", "skip"):
            s.kind = parent.kind
        return s

    def add_item(spec: Spec, src: list[Line], optional: bool = False) -> Item:
        nonlocal last_item
        fn_opt = any(f"fn{m}" in x.tags for x in src for m in optional_marks)
        it = Item(spec=spec, lines=src, optional=optional or cur.optional or fn_opt)
        if cur.pending_cond:
            cur.conds[id(it)] = cur.pending_cond
        cur.entries.append(it)
        last_item = it
        return it

    i = 0
    while i < len(lines):
        ln = lines[i]
        i += 1
        if ln.consumed:
            if ln in tlines and cur.entries:
                cur = Section(title="Szczegóły wniosku", lines=[ln])
                sections.append(cur)
                last_item = None
            continue
        t = clean(ln.text)
        ft = fold(t)
        if re.fullmatch(r"\d{1,2}[.)]?|[`'\"]", t):
            continue
        if re.fullmatch(r"[^()]*\)", ln.text.strip()) and not ln.has_placeholder:
            # domknięcie nawiasu z poprzedniej linii (dopisek do nagłówka)
            if C.OPTIONAL.search(ft):
                cur.optional = True
            continue
        if ft == "dd-mm-rrrr" or re.fullmatch(r"(dd|rrrr|mm)[-./ ]?(mm|rrrr|dd)?[-./ ]?(rrrr|dd)?", ft):
            if last_item:
                last_item.spec.type = "DATEPICKER"
                last_item.lines.append(ln)
            continue
        if PAGE_NO.match(ft) or (len(t) <= 1 and not ln.has_placeholder and ln.kind != "checkbox"):
            continue
        if FOOTNOTE_MARK.match(ln.text.strip()):
            mark = ln.text.strip()[:-1].strip()
            if mark in optional_marks and last_item and abs(last_item.lines[-1].y - ln.y) < 30:
                last_item.optional = True
            continue
        h = _is_heading(ln, mf) if ln.kind != "checkbox" else None
        if h and cur.kind == "consent" and not cur.texts and not HEADING_NUM.match(ln.text.strip()):
            # podtytuł bezpośrednio pod 'KLAUZULA INFORMACYJNA' – część tej samej sekcji
            cur.lines.append(ln)
            continue
        strong = (
            ln.bold
            or ln.heading
            or ln.text.isupper()
            or (ln.font is not None and ln.font > 1.1 * mf)
            or bool(HEADING_NUM.match(ln.text.strip()))
        )
        if h and cur.kind in ("consent", "skip") and not strong:
            h = None  # '- przez e-mail:' w treści klauzuli to nie nowa sekcja
        if h:
            cur = new_section(h[1], h[0], ln)
            if C.OPTIONAL.search(fold(ln.text)):
                cur.optional = True
            sections.append(cur)
            if C.CHOICE_HINT.search(fold(ln.text)):
                cur.choice_mode = True
            last_item = None
            if cur.kind not in ("skip", "consent") and not cur.choice_mode and _starts_list(ln, lines, i):
                cur.list_choice = Choice(title=_sentence(t), lines=[ln], multi=bool(C.MULTI_HINT.search(ft)))
                cur.entries.append(cur.list_choice)
            continue
        if cur.kind == "skip":
            continue
        if cur.kind == "consent":
            cur.texts.append(ln)
            continue
        if cur.list_choice is not None:
            lc = cur.list_choice
            nxt_input = i < len(lines) and lines[i].only_placeholder and not lines[i].consumed
            if t[:1].islower() and len(t) < 200 and not ln.has_placeholder and ln.kind != "checkbox" and not nxt_input:
                lc.options.append((_sentence(t), ln))
                lc.lines.append(ln)
                continue
            cur.list_choice = None
            if nxt_input and t[:1].islower() and len(t.split()) <= 3 and lc.options:
                ln.block_ids = ln.block_ids + lines[i].block_ids
                lines[i].consumed = True
                ln.tags.add("input")
            if t[:1].islower() and ln.has_placeholder and len(t.split()) <= 3 and lc.options:
                # ostatnia pozycja 'inne ……' – opcja + pole tekstowe widoczne po jej wybraniu
                lc.options.append((_sentence(t), ln))
                lc.lines.append(ln)
                it = add_item(Spec(_sentence(t), reason="pozycja 'inne' wyliczenia z miejscem do wpisania"), [ln])
                cur.conds[id(it)] = (lc, _sentence(t))
                continue
            if not lc.options:
                cur.entries.remove(lc)
        if C.CONDITION.match(ft):
            prev_choice = next((e for e in reversed(cur.entries) if isinstance(e, Choice)), None)
            if prev_choice and prev_choice.options:
                val = "Tak" if re.search(r"\btak\b", ft) else prev_choice.options[-1][0]
                cur.pending_cond = (prev_choice, val)
                cur.choice_mode = False
            continue
        # pole wyboru
        if ln.kind == "checkbox" or (cur.choice_mode and not ln.has_placeholder and 1 < len(t) < 160):
            label = t or "Opcja"
            if cur.kind == "attach":
                add_item(
                    Spec(_sentence(label), "FILE_UPLOADER", group="attachment", reason="pozycja listy załączników"),
                    [ln],
                )
                continue
            ch = cur.entries[-1] if cur.entries and isinstance(cur.entries[-1], Choice) else None
            if ch is None:
                q = cur.title
                if (
                    last_item
                    and last_item.spec.type == "TEXT_FIELD"
                    and not any(x.has_placeholder for x in last_item.lines)
                ):
                    cur.entries.remove(last_item)
                    q = last_item.spec.title
                ch = Choice(
                    title=q, lines=[], multi=bool(C.MULTI_HINT.search(fold(" ".join(x.text for x in cur.lines))))
                )
                if cur.pending_cond:
                    cur.conds[id(ch)] = cur.pending_cond
                cur.entries.append(ch)
                last_item = None
            ch.options.append((re.sub(r"^[☐☑□■✓✗xX]\s*", "", label), ln))
            ch.lines.append(ln)
            continue
        hint = PAREN_HINT.match(t) or PAREN_HINT.match(ln.text.strip())
        if ln.only_placeholder:
            nxt = None
            for x in lines[i : i + 4]:
                if x.consumed:
                    continue
                if x.has_placeholder or x.kind == "checkbox":
                    break
                if PAREN_HINT.match(x.text.strip()):
                    nxt = x
                    break
                # tekst innej kolumny (np. adres organu obok linii wnioskodawcy) – pomiń tylko, gdy krótki
                if len(clean(x.text)) > 40 or (x.bbox and ln.bbox and abs(x.x - ln.x) < 60):
                    break
            plabel: str | None = None
            src = [ln]
            if nxt and PAREN_HINT.match(nxt.text.strip()) and nxt.y - ln.y < 40:
                plabel = hint_text(PAREN_HINT.match(nxt.text.strip()))  # type: ignore[arg-type]
                src.append(nxt)
                nxt.consumed = True
            elif last_item and last_item.lines[-1].text.strip().endswith(":"):
                last_item.lines.append(ln)
                continue
            if plabel is None:
                continue
            specs = C.specs_for_label(plabel)
            for sp in specs:
                add_item(sp, src)
            continue
        if hint:
            if last_item and abs(last_item.lines[-1].y - ln.y) < 40:
                last_item.spec.reason += f"; podpowiedź: {hint_text(hint)}"
            elif doc.ocr and not C.DROP.search(fold(hint_text(hint))):
                # skan: OCR gubi wykropkowanie nad podpisem '(imię i nazwisko)' – podpis sam wyznacza pole
                for sp in C.specs_for_label(hint_text(hint)):
                    sp.confidence = min(sp.confidence, 0.65)
                    sp.reason += "; podpis pod brakującym w OCR miejscem do wpisania"
                    add_item(sp, [ln])
            continue
        if ln.has_placeholder:
            prev_date = False
            for lab in _labels_from_line(ln):
                lab = lab.replace("*", "").strip()
                specs = C.specs_for_label(lab)
                typed = [sp for sp in specs if sp.type != "TEXT_FIELD" or sp.validation]
                if len(lab.split()) >= 5 and typed and typed[0].type == "DATEPICKER" and fold(lab).endswith(" od"):
                    typed[0].title = "Data od"
                    specs = typed[:1]
                elif len(lab.split()) >= 5 and not typed and not C.NAME_PAIR.search(fold(lab)):
                    # luka w treści zdania ('Proszę o wynajem … w ____') – jedno pole, tytuł do sprawdzenia
                    add_item(
                        Spec(_sentence(lab)[:120], confidence=0.55, reason="pole w treści zdania – sprawdź tytuł"), [ln]
                    )
                    prev_date = False
                    continue
                if prev_date and fold(lab) in ("do", "od", "i"):
                    add_item(Spec(f"Data {lab.lower()}", "DATEPICKER", reason="zakres dat 'od … do …'"), [ln])
                    continue
                for sp in specs:
                    add_item(sp, [ln])
                prev_date = bool(specs) and specs[-1].type == "DATEPICKER"
            continue
        # etykieta bez miejsca do wpisania: komórka tabeli lub krótka linia (pole po prawej / poniżej)
        words = t.split()
        if (
            re.search(r",\s*[`'\"]?\s*$", ln.text)
            and i < len(lines)
            and lines[i].text[:1].islower()
            and abs(lines[i].y - ln.y) < 20
        ):
            t = clean(t + " " + lines[i].text)
            ln.block_ids = ln.block_ids + lines[i].block_ids
            lines[i].consumed = True
            words = t.split()
        if ln.text.rstrip(" *").endswith(":") and len(t) <= 120 and _starts_list(ln, lines, i):
            cur.list_choice = Choice(title=_sentence(t), lines=[ln], multi=bool(C.MULTI_HINT.search(ft)))
            if cur.pending_cond:
                cur.conds[id(cur.list_choice)] = cur.pending_cond
            cur.entries.append(cur.list_choice)
            last_item = None
            continue
        before_input = i < len(lines) and lines[i].only_placeholder and not lines[i].consumed
        if (
            len(t) <= 70
            and (len(words) <= 6 or ln.kind == "cell")
            and not t.endswith((".", ")"))
            and (t[:1].isupper() or t[:1].isdigit() or ln.kind == "cell" or before_input)
        ):
            if before_input:
                t = re.sub(r"^(w|we|przy|z|o|na|do|od|i)\s+", "", t, flags=re.I)  # 'w miejscowości ____'
                lines[i].consumed = True
                ln.block_ids = ln.block_ids + lines[i].block_ids
            for sp in C.specs_for_label(t):
                if ln.kind != "cell":
                    sp.confidence = min(sp.confidence, 0.78)
                add_item(sp, [ln])
            continue
        # dłuższy tekst: opis sekcji / blok tekstu
        cur.texts.append(ln)

    return _assemble(title, tconf, tlines, organ, sections, key)


def _field(spec: Spec, key: str, src: list[Line], required: bool) -> DraftField:
    conf = spec.confidence * min((ln.conf for ln in src), default=1.0)
    req: list[Validator] = ["REQUIRED"] if required else []
    return DraftField(
        key=key,
        type=spec.type,
        title=spec.title,
        validation=req + [v for v in spec.validation if v != "REQUIRED"],
        confidence=round(conf, 2),
        evidence=_ev(src, spec.reason or "etykieta w dokumencie")
        if spec.from_doc
        else [Evidence(by="rules", reason=spec.reason)],
    )


def _assemble(
    title: str,
    tconf: float,
    tlines: list[Line],
    organ: tuple[str, list[Line]] | None,
    sections: list[Section],
    key: _Keys,
) -> DraftForm:
    data: list[DraftField] = []  # sekcje zakładki "Dane"
    details: list[DraftField] = []
    contact: list[DraftField] = []
    consents: list[DraftField] = []

    if organ:
        f = DraftField(
            key=key(),
            type="TEXT_FIELD",
            title="Nazwa organu",
            read_only=True,
            default_value=organ[0],
            confidence=0.85,
            evidence=_ev(organ[1], "adresat wniosku z nagłówka dokumentu"),
        )
        data.append(
            DraftField(
                key=key(),
                type="SECTION",
                title="Organ, do którego jest składany wniosek",
                children=[f],
                confidence=0.85,
                evidence=_ev(organ[1], "adresat wniosku"),
            )
        )

    proxy_switch: DraftField | None = None
    if any(s.kind == "proxy" and s.entries for s in sections):
        proxy_switch = DraftField(
            key=key(),
            type="RADIO",
            title="Czy wniosek składa pełnomocnik?",
            options=[DraftOption(name="Nie"), DraftOption(name="Tak")],
            validation=["REQUIRED"],
            confidence=0.55,
            evidence=[Evidence(by="rules", reason="dokument zawiera sekcję pełnomocnika – dodano przełącznik (SHOW)")],
        )
        data.append(
            DraftField(
                key=key(),
                type="SECTION",
                title="Podmiot wniosku",
                children=[proxy_switch],
                confidence=0.55,
                evidence=list(proxy_switch.evidence),
            )
        )

    for s in sections:
        if s.kind == "skip":
            continue
        if s.kind == "consent":
            txt = " ".join(clean(x.text) for x in s.texts)
            if not txt and not s.entries:
                continue
            consents.append(_consent_section(s, txt, key))
            continue
        if not s.entries and not s.texts and s.lines:
            # pusta sekcja z samym nagłówkiem (np. "4. Uzasadnienie wniosku") – pole z tytułu
            for sp in C.specs_for_label(s.title):
                if sp.type in ("TEXTAREA", "DATEPICKER", "NUMBER"):
                    sp.reason = "pole wynika z nagłówka sekcji (miejsce do wpisania pod nagłówkiem)"
                    sp.confidence = 0.7
                    s.entries.append(Item(spec=sp, lines=list(s.lines), optional=s.optional))
        if not s.entries:
            continue
        addr_ok = (
            s.kind in ("person", "proxy", "")
            and (s.kind != "" or "adres" in fold(s.title) or fold(s.title) == "dane wniosku")
            or "adres" in fold(s.title)
        )
        # podział mieszanych grup (osoba / adres / kontakt) na osobne sekcje
        buckets: dict[str, list[DraftField]] = {}
        order: list[str] = []
        addr_found: dict[str, list[Item]] = {}
        choice_fields: dict[int, DraftField] = {}
        items_by_field: dict[str, Item | Choice] = {}
        for e in s.entries:
            if isinstance(e, Choice):
                df = DraftField(
                    key=key(),
                    type="CHECKBOX" if e.multi else "RADIO",
                    title=_sentence(e.title),
                    options=[DraftOption(name=_sentence(n), checked=ln.checked) for n, ln in e.options],
                    validation=["REQUIRED"],
                    confidence=0.85 if all(ln.kind == "checkbox" for _, ln in e.options) else 0.55,
                    evidence=_ev(
                        e.lines,
                        "opcje z pól wyboru w dokumencie"
                        if all(ln.kind == "checkbox" for _, ln in e.options)
                        else "opcje z listy po instrukcji 'zaznacz' (brak wykrytych kratek)",
                    ),
                )
                choice_fields[id(e)] = df
                items_by_field[df.key] = e
                g = ""
            else:
                g = e.spec.group
                if (
                    fold(e.spec.title) in SUBMISSION_META or SUBMISSION_PLACE_DATE.match(fold(e.spec.title))
                ) and s.kind in (
                    "",
                    "person",
                ):
                    continue  # data/miejsce złożenia – nadaje system
                if g == "address" and not addr_ok:
                    g = ""
                elif g == "address":
                    addr_found.setdefault(e.spec.title, []).append(e)
                    if "address" not in order:
                        order.append("address")
                    continue
                df = _field(
                    e.spec, key(), e.lines, required=not (e.optional or s.optional) and e.spec.type != "TEXT_BLOCK"
                )
                items_by_field[df.key] = e
            if g == "attachment":
                g = ""
            if g not in order:
                order.append(g)
            buckets.setdefault(g, []).append(df)
        if addr_found:
            buckets["address"] = _address_fields(addr_found, key, s.optional)
        # warunki SHOW z "Jeśli wybierzesz…"
        for df in [x for b in buckets.values() for x in b]:
            src_e = items_by_field.get(df.key)
            if src_e is not None and id(src_e) in s.conds:
                cond_choice, val = s.conds[id(src_e)]
                trg = choice_fields.get(id(cond_choice))
                if trg:
                    df.show_when.append(ShowWhen(when_key=trg.key, equals=_sentence(val)))
                    df.evidence.append(Evidence(by="rules", reason=f"widoczne gdy '{trg.title}' = '{_sentence(val)}'"))
        if s.texts:
            desc = " ".join(clean(x.text) for x in s.texts)[:1000]
            if desc:
                tb = DraftField(
                    key=key(),
                    type="TEXT_BLOCK",
                    title="",
                    description=desc,
                    confidence=0.8,
                    evidence=_ev(s.texts, "tekst informacyjny sekcji"),
                )
                buckets.setdefault("", []).insert(0, tb)
                if "" not in order:
                    order.insert(0, "")
        for g in order:
            ch = buckets.get(g) or []
            if not ch:
                continue
            st = s.title
            if len(order) > 1 and g == "address":
                st = "Adres zamieszkania" if s.kind in ("person", "") else f"Adres – {s.title.lower()}"
            elif len(order) > 1 and g == "contact":
                st = "Dane do kontaktu"
            elif len(order) > 1 and g == "person" and s.kind in ("person", ""):
                st = "Twoje dane" if s.kind == "person" or fold(s.title) == "dane wniosku" else s.title
            sec = DraftField(
                key=key(),
                type="SECTION",
                title=st,
                children=ch,
                confidence=round(min(0.95, sum(c.confidence for c in ch) / len(ch)), 2),
                evidence=_ev(s.lines, "nagłówek sekcji w dokumencie")
                if s.lines
                else [Evidence(by="rules", reason="grupa pól")],
            )
            if s.kind == "proxy" and proxy_switch:
                sec.show_when.append(ShowWhen(when_key=proxy_switch.key, equals="Tak"))
            if g == "contact" or s.kind == "contact":
                contact.append(sec)
            elif g in ("person", "address") or s.kind in ("person", "proxy"):
                data.append(sec)
            else:
                details.append(sec)
            if s.kind == "attach" and proxy_switch:
                for c in ch:
                    if "pelnomocn" in fold(c.title):
                        c.show_when.append(ShowWhen(when_key=proxy_switch.key, equals="Tak"))

    tabs: list[DraftTab] = []
    if data:
        tabs.append(DraftTab(title="Dane", fields=data, confidence=0.8))
    if details:
        tabs.append(DraftTab(title="Szczegóły wniosku", fields=details, confidence=0.7))
    if contact or consents:
        tabs.append(DraftTab(title="Kontakt i zgody", fields=contact + consents, confidence=0.75))
    if not tabs:
        tabs.append(DraftTab(title="Dane", confidence=0.3))
    summary = DraftField(
        key=key(),
        type="INFO_SECTION",
        title="Podgląd",
        description="Sprawdź podgląd uzupełnionego wniosku przed wysłaniem.",
        confidence=1.0,
        evidence=[Evidence(by="rules", reason="standard: strona końcowa z podglądem")],
    )
    tabs.append(
        DraftTab(
            title="Strona końcowa",
            type="FINISH",
            fields=[
                DraftField(
                    key=key(),
                    type="SECTION",
                    title="Podgląd uzupełnionego wniosku",
                    children=[summary],
                    confidence=1.0,
                    evidence=list(summary.evidence),
                )
            ],
        )
    )
    return DraftForm(
        title=title,
        title_confidence=tconf,
        title_evidence=_ev(tlines, "tytuł z nagłówka dokumentu")
        if tlines
        else [Evidence(by="rules", reason="tytuł z nazwy pliku")],
        tabs=tabs,
    )


def _address_fields(found: dict[str, list[Item]], key: _Keys, optional: bool) -> list[DraftField]:
    std = C.address_set("uzupełniono wg standardu adresu eUsługi (kraj + adres krajowy/zagraniczny)", set(found))
    # jeżeli dokument ma tylko pojedyncze ogólne "adres" – w found nie ma składników
    by_title: dict[str, DraftField] = {}
    out: list[DraftField] = []
    for sp in std:
        parts = C.TERYT_PARTS if sp.title == C.TERYT_DICT else (sp.title,)
        hits = [it for t in parts for it in found.get(t, [])]
        src = [ln for it in hits for ln in it.lines]
        if hits and sp.title == C.TERYT_DICT:
            sp.confidence = max(sp.confidence, min(0.85, hits[0].spec.confidence))
        elif found.get(sp.title):
            sp.from_doc = True
            sp.confidence = max(sp.confidence, found[sp.title][0].spec.confidence)
            sp.reason = found[sp.title][0].spec.reason or "składnik adresu"
        elif any(it.spec.reason.startswith("rozwinięto") for its in found.values() for it in its):
            sp.from_doc = False
        req = not optional and sp.title != "Numer lokalu"
        df = _field(sp, key(), src, required=req)
        if not sp.from_doc:
            gen = [ln for its in found.values() for it in its for ln in it.lines]
            df.evidence = _ev(gen, sp.reason) if gen else df.evidence
        if sp.title == "Kraj":
            df.default_value = ["Polska"]
            df.dictionary_name = "Kraje"
        elif sp.title == C.TERYT_DICT:
            df.dictionary_name = C.TERYT_DICT
            df.multi_level_tree = True
        by_title[sp.title] = df
        out.append(df)
    for df, sp in zip(out, std, strict=True):
        if sp.show_when:
            trg = by_title[sp.show_when[0]]
            df.show_when.append(ShowWhen(when_key=trg.key, equals=sp.show_when[1], negate=sp.show_when[2]))
    return out


def _consent_section(s: Section, txt: str, key: _Keys) -> DraftField:
    desc = txt[:600] + ("…" if len(txt) > 600 else "")
    consent = DraftField(
        key=key(),
        type="CONSENT_SECTION",
        title="",
        consent_section_config=ConsentSectionConfig(
            consents=[
                Consent(
                    description="Potwierdzam zapoznanie się z informacją o przetwarzaniu danych osobowych."
                    if C.SECTION_CONSENT.search(fold(s.title + " " + txt))
                    else _sentence(s.title)
                )
            ],
            required=True,
        ),
        description=desc,
        validation=["REQUIRED"],
        confidence=0.7,
        evidence=_ev(s.lines + s.texts[:5], "klauzula/oświadczenie w dokumencie -> sekcja zgód"),
    )
    return DraftField(
        key=key(),
        type="SECTION",
        title="Zgody i oświadczenia",
        children=[consent],
        confidence=0.7,
        evidence=list(consent.evidence),
    )
