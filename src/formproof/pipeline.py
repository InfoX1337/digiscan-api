"""Pipeline: extract -> infer -> llm -> dict -> build -> validate -> report.

Każdy krok to czysta funkcja z formproof/<krok>/__init__.py (kontrakt: types/stages.py).
"""

from __future__ import annotations

import base64
import io
import time
from collections.abc import Callable
from dataclasses import dataclass

from . import build as build_mod
from . import dictionaries as dict_mod
from . import extract as extract_mod
from . import infer as infer_mod
from . import llm as llm_mod
from . import validate as validate_mod
from .config import Settings
from .ingest import IngestedFile, IngestError
from .types.draft import DraftField, DraftForm, iter_draft
from .types.form import FormDefinition, Question, iter_questions
from .types.report import (
    FieldReport,
    LlmInfo,
    PagePreview,
    ProposedDictionary,
    Repair,
    Report,
    ReviewItem,
    RuleResult,
    SourceRef,
)
from .types.source import BBox, SourceBlock, SourceDoc
from .types.stages import ExtractInput

REVIEW_THRESHOLD = 0.6  # poniżej – pole trafia na listę "Do przeglądu"


class Timeout(Exception):
    pass


@dataclass
class ConvertOptions:
    llm: bool = True
    previews: bool = False


@dataclass
class ConvertResult:
    form: FormDefinition
    report: Report

    def dump(self) -> dict[str, object]:
        return {"form": self.form.dump(), "report": self.report.model_dump(mode="json", exclude_none=True)}


def _timed[R](timings: dict[str, int], name: str, fn: Callable[[], R]) -> R:
    t0 = time.perf_counter()
    try:
        return fn()
    finally:
        timings[name] = round((time.perf_counter() - t0) * 1000)


def convert(file: IngestedFile, cfg: Settings, opts: ConvertOptions) -> ConvertResult:
    deadline = time.monotonic() + cfg.request_timeout_s
    timings: dict[str, int] = {}
    doc = _timed(
        timings,
        "extract",
        lambda: extract_mod.extract(
            ExtractInput(
                filename=file.filename,
                format=file.format,
                data=file.data,
                max_ocr_pages=cfg.max_ocr_pages,
                deadline=deadline,
            )
        ),
    )
    if not doc.blocks:
        raise IngestError("NOTHING_EXTRACTED", "Nie udało się odczytać treści z pliku.", 422)
    if time.monotonic() > deadline:
        raise Timeout()

    draft = _timed(timings, "infer", lambda: infer_mod.infer(doc))

    llm = LlmInfo()
    if opts.llm and cfg.llm_enabled:
        r = _timed(timings, "llm", lambda: llm_mod.enrich(doc, draft))
        draft = r.draft
        llm = LlmInfo(used=r.used, model=r.model, error=r.error)

    d = _timed(timings, "dict", lambda: dict_mod.apply_dictionaries(draft))
    draft = d.draft
    built = _timed(timings, "build", lambda: build_mod.build(draft))
    v = _timed(timings, "validate", lambda: validate_mod.validate(built.form, repair=True))

    proposed = [
        ProposedDictionary(name=p.name, field_id=built.key_to_id.get(p.field_key, ""), items=p.items, reason=p.reason)
        for p in d.proposed
    ]
    report = assemble_report(doc, draft, built.key_to_id, v.form, v.rules, v.repairs, proposed, timings, llm)
    if opts.previews:
        report.previews = render_previews(file, doc, cfg.max_ocr_pages)
    return ConvertResult(form=v.form, report=report)


def _union(bs: list[BBox]) -> BBox | None:
    if not bs:
        return None
    x = min(b.x for b in bs)
    y = min(b.y for b in bs)
    return BBox(x=x, y=y, w=max(b.x + b.w for b in bs) - x, h=max(b.y + b.h for b in bs) - y)


def assemble_report(
    doc: SourceDoc,
    draft: DraftForm,
    key_to_id: dict[str, str],
    form: FormDefinition,
    rules: list[RuleResult],
    repairs: list[Repair],
    proposed: list[ProposedDictionary],
    timings: dict[str, int],
    llm: LlmInfo,
) -> Report:
    blocks: dict[str, SourceBlock] = {b.id: b for b in doc.blocks}
    by_id: dict[str, DraftField] = {}
    for t in draft.tabs:
        for f in iter_draft(t.fields):
            if f.key in key_to_id:
                by_id[key_to_id[f.key]] = f

    fields: dict[str, FieldReport] = {}
    review: list[ReviewItem] = []
    w_sum = c_sum = 0.0
    all_q: list[Question] = [q for t in form.tabs for q in iter_questions(t.questions)]
    for q in all_q:
        f = q.field
        dr = by_id.get(f.id)
        ids = list(dict.fromkeys(bid for e in (dr.evidence if dr else []) for bid in e.block_ids))
        src = [blocks[i] for i in ids if i in blocks]
        sources: list[SourceRef] = []
        for page in dict.fromkeys(b.page for b in src):
            bs = [b for b in src if b.page == page]
            sources.append(
                SourceRef(
                    page=page,
                    bbox=_union([b.bbox for b in bs if b.bbox]),
                    text=" ".join(b.text for b in bs)[:500],
                    block_ids=[b.id for b in bs],
                )
            )
        conf = dr.confidence if dr else 1.0  # brak draftu = dodane przez auto-naprawę
        fields[f.id] = FieldReport(
            id=f.id,
            tech_name=f.tech_name,
            title=f.title,
            type=f.type,
            confidence=round(conf, 2),
            sources=sources,
            decided_by=list(dict.fromkeys(e.by for e in dr.evidence)) if dr else ["repair"],
            reasons=[e.reason for e in dr.evidence if e.reason] if dr else ["dodane przez auto-naprawę"],
        )
        if dr:
            w = 0.5 if f.type == "SECTION" else 1.0
            w_sum += w
            c_sum += w * conf
            if conf < REVIEW_THRESHOLD:
                reason = next((e.reason for e in reversed(dr.evidence) if e.reason), "niska pewność")
                review.append(
                    ReviewItem(
                        field_id=f.id, tech_name=f.tech_name, title=f.title, confidence=round(conf, 2), reason=reason
                    )
                )
    review.sort(key=lambda r: r.confidence)
    return Report(
        filename=doc.filename,
        format=doc.format,
        ocr=doc.ocr,
        confidence=round(c_sum / w_sum, 2) if w_sum else 0.0,
        fields=fields,
        review=review,
        rules=rules,
        repairs=repairs,
        proposed_dictionaries=proposed,
        warnings=doc.warnings,
        timings=timings,
        llm=llm,
    )


def render_previews(file: IngestedFile, doc: SourceDoc, max_pages: int) -> list[PagePreview]:
    """PNG stron oryginału (PDF/obraz) dla podświetlania w UI. bbox w jednostkach SourcePage.width/height."""
    from PIL import Image

    out: list[PagePreview] = []

    def enc(img: Image.Image, page: int, w: float, h: float) -> None:
        img.thumbnail((1400, 1400 * 2))
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="PNG", optimize=True)
        out.append(PagePreview(page=page, width=w, height=h, png_base64=base64.b64encode(buf.getvalue()).decode()))

    if file.format == "pdf":
        import pypdfium2 as pdfium

        pdf = pdfium.PdfDocument(file.data)
        try:
            for i in range(min(len(pdf), max_pages)):
                page = pdf[i]
                w, h = page.get_size()
                enc(page.render(scale=2).to_pil(), i + 1, w, h)
        finally:
            pdf.close()
    elif file.format == "image":
        img = Image.open(io.BytesIO(file.data))
        enc(img.copy(), 1, float(img.width), float(img.height))
    return out
