/**
 * Pipeline: extract → infer → llm → dict → build → validate → report.
 * Każdy krok to czysta funkcja z src/<krok>/index.ts (kontrakt: src/types/stages.ts).
 */
import { extract } from './extract/index.js';
import { infer } from './infer/index.js';
import { enrich } from './llm/index.js';
import { applyDictionaries } from './dict/index.js';
import { build } from './build/index.js';
import { validate } from './validate/index.js';
import type { Config } from './config.js';
import type { IngestedFile } from './ingest/index.js';
import { IngestError } from './ingest/index.js';
import type { SourceDoc } from './types/source.js';
import type { DraftField, DraftForm } from './types/draft.js';
import type { ConvertResponse, FieldReport, Report, ReviewItem, SourceRef } from './types/report.js';
import type { Question } from './types/form.js';

/** poniżej tego progu pole trafia na listę "Do przeglądu" */
export const REVIEW_THRESHOLD = 0.6;

export interface ConvertOptions {
  llm: boolean;
  signal?: AbortSignal;
}

async function timed<T>(timings: Record<string, number>, name: string, fn: () => T | Promise<T>): Promise<T> {
  const t0 = performance.now();
  try {
    return await fn();
  } finally {
    timings[name] = Math.round(performance.now() - t0);
  }
}

export async function convert(file: IngestedFile, cfg: Config, opts: ConvertOptions): Promise<ConvertResponse> {
  const timings: Record<string, number> = {};
  const doc = await timed(timings, 'extract', () =>
    extract({ filename: file.filename, format: file.format, bytes: file.bytes, maxOcrPages: cfg.maxOcrPages, signal: opts.signal }),
  );
  if (doc.blocks.length === 0) {
    throw new IngestError('NOTHING_EXTRACTED', 'Nie udało się odczytać treści z pliku.', 422);
  }
  let draft = await timed(timings, 'infer', () => infer(doc));

  let llm: Report['llm'] = { used: false };
  if (opts.llm && cfg.llm.enabled) {
    const r = await timed(timings, 'llm', () => enrich(doc, draft, { signal: opts.signal }));
    draft = r.draft;
    llm = { used: r.used, ...(r.model ? { model: r.model } : {}), ...(r.error ? { error: r.error } : {}) };
  }

  const dict = await timed(timings, 'dict', () => applyDictionaries(draft));
  draft = dict.draft;

  const built = await timed(timings, 'build', () => build(draft));
  const validated = await timed(timings, 'validate', () => validate(built.form, { repair: true }));

  const report = assembleReport(doc, draft, built.keyToId, validated.form.tabs.flatMap((t) => t.questions), {
    rules: validated.rules,
    repairs: validated.repairs,
    proposed: dict.proposed.map(({ fieldKey, ...p }) => ({ ...p, fieldId: built.keyToId[fieldKey] ?? '' })),
    timings,
    llm,
  });
  return { form: validated.form, report };
}

function flattenDraft(fields: DraftField[], out: DraftField[] = []): DraftField[] {
  for (const f of fields) {
    out.push(f);
    if (f.children) flattenDraft(f.children, out);
  }
  return out;
}

function* walk(qs: Question[]): Generator<Question> {
  for (const q of qs) {
    yield q;
    yield* walk(q.field.repeatingSectionGrid ?? []);
  }
}

function unionBBox(refs: { bbox?: SourceRef['bbox'] }[]): SourceRef['bbox'] | undefined {
  const bs = refs.map((r) => r.bbox).filter((b): b is NonNullable<typeof b> => !!b);
  if (!bs.length) return undefined;
  const x = Math.min(...bs.map((b) => b.x));
  const y = Math.min(...bs.map((b) => b.y));
  return {
    x,
    y,
    w: Math.max(...bs.map((b) => b.x + b.w)) - x,
    h: Math.max(...bs.map((b) => b.y + b.h)) - y,
  };
}

export function assembleReport(
  doc: SourceDoc,
  draft: DraftForm,
  keyToId: Record<string, string>,
  questions: Question[],
  extra: Pick<Report, 'rules' | 'repairs' | 'timings' | 'llm'> & { proposed: Report['proposedDictionaries'] },
): Report {
  const blocks = new Map(doc.blocks.map((b) => [b.id, b]));
  const byId = new Map<string, DraftField>();
  for (const f of flattenDraft(draft.tabs.flatMap((t) => t.fields))) {
    const id = keyToId[f.key];
    if (id) byId.set(id, f);
  }
  const fields: Record<string, FieldReport> = {};
  const review: ReviewItem[] = [];
  let wSum = 0;
  let cSum = 0;
  for (const q of questions.flatMap((q) => [...walk([q])])) {
    const f = q.field;
    const d = byId.get(f.id);
    const ids = [...new Set(d?.evidence.flatMap((e) => e.blockIds) ?? [])];
    const srcBlocks = ids.map((id) => blocks.get(id)).filter((b): b is NonNullable<typeof b> => !!b);
    // jedno źródło na stronę (zwykle pole leży na jednej stronie)
    const pages = [...new Set(srcBlocks.map((b) => b.page))];
    const sources: SourceRef[] = pages.map((p) => {
      const bs = srcBlocks.filter((b) => b.page === p);
      const bbox = unionBBox(bs);
      return { page: p, ...(bbox ? { bbox } : {}), text: bs.map((b) => b.text).join(' ').slice(0, 500), blockIds: bs.map((b) => b.id) };
    });
    // pole bez draftu = dodane przez auto-naprawę (np. strona końcowa)
    const confidence = d ? d.confidence : 1;
    const decidedBy = d ? [...new Set(d.evidence.map((e) => e.by))] : (['repair'] as const);
    fields[f.id] = {
      id: f.id,
      techName: f.techName,
      title: f.title,
      type: f.type,
      confidence: Math.round(confidence * 100) / 100,
      sources,
      decidedBy: [...decidedBy],
      reasons: d ? d.evidence.map((e) => e.reason).filter((r): r is string => !!r) : ['dodane przez auto-naprawę'],
    };
    if (d) {
      const w = f.type === 'SECTION' ? 0.5 : 1;
      wSum += w;
      cSum += w * confidence;
      if (confidence < REVIEW_THRESHOLD) {
        review.push({
          fieldId: f.id,
          techName: f.techName,
          title: f.title,
          confidence: fields[f.id]!.confidence,
          reason: d.evidence.at(-1)?.reason ?? 'niska pewność',
        });
      }
    }
  }
  review.sort((a, b) => a.confidence - b.confidence);
  return {
    filename: doc.filename,
    format: doc.format,
    ocr: doc.ocr,
    confidence: wSum ? Math.round((cSum / wSum) * 100) / 100 : 0,
    fields,
    review,
    rules: extra.rules,
    repairs: extra.repairs,
    proposedDictionaries: extra.proposed,
    warnings: doc.warnings,
    timings: extra.timings,
    llm: extra.llm,
  };
}
