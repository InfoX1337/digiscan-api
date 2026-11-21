"""OCR (pytesseract) dla obrazów i PDF bez warstwy tekstu."""

from __future__ import annotations

import io
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


def ocr_lines(img: Image.Image, lang: str, scale: float = 1.0) -> list[OcrLine]:
    import pytesseract

    data = pytesseract.image_to_data(img, lang=lang, output_type=pytesseract.Output.DICT)
    groups: dict[tuple[int, int, int], list[int]] = defaultdict(list)
    for i, t in enumerate(data["text"]):
        try:
            conf = float(data["conf"][i])
        except TypeError, ValueError:
            conf = -1
        if t and t.strip() and conf >= 0:
            groups[(data["block_num"][i], data["par_num"][i], data["line_num"][i])].append(i)
    lines: list[OcrLine] = []
    for idxs in groups.values():
        idxs.sort(key=lambda i: data["left"][i])
        x0 = min(data["left"][i] for i in idxs)
        y0 = min(data["top"][i] for i in idxs)
        x1 = max(data["left"][i] + data["width"][i] for i in idxs)
        y1 = max(data["top"][i] + data["height"][i] for i in idxs)
        conf = sum(float(data["conf"][i]) for i in idxs) / len(idxs) / 100
        text = " ".join(data["text"][i].strip() for i in idxs)
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
    while y0 < rgb.height:
        if expired(inp.deadline):
            warnings.append("OCR: przekroczono limit czasu")
            break
        y1 = min(rgb.height, y0 + strip)
        lo = y0 + (overlap / 2 if y0 > 0 else 0)
        hi = y1 - overlap / 2 if y1 < rgb.height else float(y1)
        part = rgb if (y0, y1) == (0, rgb.height) else rgb.crop((0, y0, rgb.width, y1))
        for ln in ocr_lines(part, lang):
            ln.y += y0
            if lo <= ln.y + ln.h / 2 < hi:
                lines.append(ln)
        if y1 >= rgb.height:
            break
        y0 = y1 - overlap
    add_ocr_lines(b, 1, lines)
    return SourceDoc(filename=inp.filename, format="image", ocr=True, pages=pages, blocks=b.blocks, warnings=warnings)
