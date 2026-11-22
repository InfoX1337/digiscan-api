"""OCR (pytesseract) dla obrazów i PDF bez warstwy tekstu."""

from __future__ import annotations

import io
import re
from collections import defaultdict
from dataclasses import dataclass

from PIL import Image

from ..types.source import BBox, BlockStyle, SourceDoc, SourcePage
from ..types.stages import ExtractInput
from .common import Builder, expired, segment


@dataclass
class OcrLine:
    text: str
    x: float
    y: float
    w: float
    h: float
    conf: float  # 0..1


def pick_lang(warnings: list[str]) -> str | None:
    """pol jeśli dostępny, inaczej eng (warning); None gdy brak tesseracta."""
    try:
        import pytesseract

        langs = set(pytesseract.get_languages(config=""))
    except Exception as e:  # brak binarki tesseract itp.
        warnings.append(f"OCR niedostępny: {e}")
        return None
    if "pol" in langs:
        return "pol"
    if "eng" in langs:
        warnings.append("OCR: brak języka pol, użyto eng")
        return "eng"
    warnings.append("OCR: brak języków pol/eng")
    return None


PLACEHOLDER = "……"
LOW_CONF = 60  # słowo poniżej – ponowny OCR wycinka
REOCR_OK = 75  # ponowny OCR przyjmujemy od tej średniej pewności
MAX_REOCR = 80  # limit dodatkowych wywołań tesseracta na obraz
_DOTS = re.compile(r"^[.…,_·:;'\"`\-–—|]+$")
_BOX_GLYPH = {"Q", "q", "□"}
_BOX_MAYBE = {"O", "o", "0", "D"}  # tylko przy niskiej pewności (inaczej to zwykłe 'o')
_JUNK = re.compile(r"[^\w\s.,:;()/\-–—%*\"'„”]")


def _reocr(img: Image.Image, lang: str, x: int, y: int, w: int, h: int) -> tuple[str, float]:
    """OCR pojedynczego słowa/wycinka (psm 7, powiększenie 2×). Zwraca (tekst, średnia pewność 0..100)."""
    import pytesseract

    pad_x, pad_y = 4, max(4, h // 3)
    crop = img.crop(
        (max(0, x - pad_x), max(0, y - pad_y), min(img.width, x + w + pad_x), min(img.height, y + h + pad_y))
    )
    crop = crop.resize((crop.width * 2, crop.height * 2))
    r = pytesseract.image_to_data(crop, lang=lang, config="--psm 7", output_type=pytesseract.Output.DICT)
    ws = [(r["text"][j].strip(), float(r["conf"][j])) for j in range(len(r["text"])) if r["text"][j].strip()]
    if not ws:
        return "", 0.0
    return " ".join(t for t, _ in ws), sum(c for _, c in ws) / len(ws)


def _clean_words(
    img: Image.Image, lang: str, words: list[tuple[str, float, int, int, int, int]], budget: list[int], mh: float
) -> tuple[str, float]:
    """Słowa jednej linii -> (tekst, pewność 0..1). Wykropkowania -> '……', szum -> ponowny OCR albo usunięcie.

    `mh` – mediana wysokości słów na stronie (wykropkowania są dużo niższe niż litery).
    """
    out: list[str] = []
    confs: list[float] = []
    for k, (t, conf, x, y, w, h) in enumerate(words):
        nxt = words[k + 1][0] if k + 1 < len(words) else ""
        if _DOTS.match(t) and len(t) >= 3 or (mh and h <= 0.35 * mh and w > 2 * h and t not in "-–—"):
            out.append(PLACEHOLDER)  # wykropkowanie / linia do wpisania
            continue
        if (t in _BOX_GLYPH or t in _BOX_MAYBE and conf < 60) and nxt[:1].islower() and 0.6 <= w / max(h, 1) <= 1.6:
            out.append("☐")  # kratka (Wingdings 'q') czytana jako 'Q'
            confs.append(max(conf, 80.0))
            continue
        if conf < LOW_CONF and budget[0] > 0 and h >= 6:
            budget[0] -= 1
            rt, rc = _reocr(img, lang, x, y, w, h)
            if (rt in _BOX_GLYPH or rt in _BOX_MAYBE) and nxt[:1].islower() and 0.6 <= w / max(h, 1) <= 1.6:
                out.append("☐")
                confs.append(80.0)
                continue
            if rt and _DOTS.match(rt.replace(" ", "")):
                out.append(PLACEHOLDER)
                continue
            junk = len(_JUNK.findall(rt)) + rt.count("_")
            if rt and rc >= REOCR_OK and rc > conf + 15 and any(c.isalnum() for c in rt) and junk <= len(rt) // 12:
                out.append(rt)
                confs.append(rc)
                continue
            if conf < 20:
                if w > 3 * h:
                    out.append(PLACEHOLDER)  # długi „wyraz” z szumu = wykropkowane miejsce do wpisania
                continue
        out.append(t)
        confs.append(conf)
    text = re.sub(rf"(?:{PLACEHOLDER}\s*)+", PLACEHOLDER + " ", " ".join(out)).strip()
    text = re.sub(r"^\|\s*|\s*\|$", "", text)  # krawędź tabeli
    return text, (sum(confs) / len(confs) / 100 if confs else 0.3)


def ocr_lines(img: Image.Image, lang: str, scale: float = 1.0, budget: list[int] | None = None) -> list[OcrLine]:
    import pytesseract

    budget = budget if budget is not None else [MAX_REOCR]
    data = pytesseract.image_to_data(img, lang=lang, output_type=pytesseract.Output.DICT)
    groups: dict[tuple[int, int, int], list[int]] = defaultdict(list)
    for i, t in enumerate(data["text"]):
        try:
            conf = float(data["conf"][i])
        except TypeError, ValueError:
            conf = -1
        if t and t.strip() and conf >= 0:
            groups[(data["block_num"][i], data["par_num"][i], data["line_num"][i])].append(i)
    hs = sorted(data["height"][i] for idxs in groups.values() for i in idxs)
    mh = float(hs[len(hs) // 2]) if hs else 0.0
    lines: list[OcrLine] = []
    for idxs in groups.values():
        idxs.sort(key=lambda i: data["left"][i])
        x0 = min(data["left"][i] for i in idxs)
        y0 = min(data["top"][i] for i in idxs)
        x1 = max(data["left"][i] + data["width"][i] for i in idxs)
        y1 = max(data["top"][i] + data["height"][i] for i in idxs)
        words = [
            (
                data["text"][i].strip(),
                float(data["conf"][i]),
                data["left"][i],
                data["top"][i],
                data["width"][i],
                data["height"][i],
            )
            for i in idxs
        ]
        text, conf = _clean_words(img, lang, words, budget, mh)
        if not text or text == PLACEHOLDER and x1 - x0 < 40:
            continue
        lines.append(OcrLine(text, x0 / scale, y0 / scale, (x1 - x0) / scale, (y1 - y0) / scale, conf))
    lines.sort(key=lambda ln: (round(ln.y / 4), ln.x))
    return lines


def add_ocr_lines(b: Builder, page: int, lines: list[OcrLine]) -> None:
    for ln in lines:
        segs = segment(ln.text)
        n = max(len(ln.text), 1)
        for s in segs:
            x = ln.x + ln.w * s.start / n
            w = ln.w * max(s.end - s.start, 1) / n
            bbox = BBox(x=x, y=ln.y, w=w, h=ln.h)
            if s.kind == "text":
                b.add(page, "text", s.text, bbox, BlockStyle(font_size=round(ln.h, 1)), confidence=ln.conf)
            elif s.kind == "checkbox":
                b.add(page, "checkbox", s.text, bbox, checked=bool(s.checked), confidence=ln.conf)
            else:
                b.add(page, "line", "", bbox, confidence=ln.conf)


def extract_image(inp: ExtractInput) -> SourceDoc:
    warnings: list[str] = []
    b = Builder()
    img = Image.open(io.BytesIO(inp.data))
    img.load()
    pages = [SourcePage(page=1, width=float(img.width), height=float(img.height))]
    lang = pick_lang(warnings)
    if lang is None:
        return SourceDoc(filename=inp.filename, format="image", ocr=True, pages=pages, blocks=[], warnings=warnings)
    rgb = img.convert("RGB")
    lines: list[OcrLine] = []
    # tesseract nie przyjmuje obrazów > 32767 px – długie skany OCR-ujemy w pasach z zakładką
    strip, overlap = 8000, 120
    y0 = 0
    budget = [MAX_REOCR]
    while y0 < rgb.height:
        if expired(inp.deadline):
            warnings.append("OCR: przekroczono limit czasu")
            break
        y1 = min(rgb.height, y0 + strip)
        lo = y0 + (overlap / 2 if y0 > 0 else 0)
        hi = y1 - overlap / 2 if y1 < rgb.height else float(y1)
        part = rgb if (y0, y1) == (0, rgb.height) else rgb.crop((0, y0, rgb.width, y1))
        for ln in ocr_lines(part, lang, budget=budget):
            ln.y += y0
            if lo <= ln.y + ln.h / 2 < hi:
                lines.append(ln)
        if y1 >= rgb.height:
            break
        y0 = y1 - overlap
    add_ocr_lines(b, 1, lines)
    return SourceDoc(filename=inp.filename, format="image", ocr=True, pages=pages, blocks=b.blocks, warnings=warnings)
