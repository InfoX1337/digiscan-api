/**
 * Sygnatury kroków pipeline'u – kontrakt między strumieniami.
 * Każdy strumień eksportuje dokładnie tę funkcję ze swojego `index.ts`.
 */
import type { SourceDoc, SourceFormat } from './source.js';
import type { DraftForm } from './draft.js';
import type { FormDefinition } from './form.js';
import type { RuleResult, Repair, ProposedDictionary } from './report.js';

export interface ExtractInput {
  filename: string;
  format: SourceFormat;
  bytes: Uint8Array;
  /** limit stron OCR */
  maxOcrPages: number;
  signal?: AbortSignal;
}
/** src/extract/index.ts */
export type ExtractFn = (input: ExtractInput) => Promise<SourceDoc>;

/** src/infer/index.ts */
export type InferFn = (doc: SourceDoc) => DraftForm;

export interface LlmResult {
  draft: DraftForm;
  used: boolean;
  model?: string;
  error?: string;
}
/** src/llm/index.ts – opcjonalne wzbogacenie; nigdy nie rzuca (fallback = draft bez zmian) */
export type EnrichFn = (doc: SourceDoc, draft: DraftForm, opts: { signal?: AbortSignal }) => Promise<LlmResult>;

/** src/dict/index.ts – słowniki, dane inicjalne, propozycje słowników */
export type DictFn = (draft: DraftForm) => { draft: DraftForm; proposed: (Omit<ProposedDictionary, 'fieldId'> & { fieldKey: string })[] };

export interface BuildResult {
  form: FormDefinition;
  /** draft key → UUID pola w form */
  keyToId: Record<string, string>;
}
/** src/build/index.ts */
export type BuildFn = (draft: DraftForm) => BuildResult;

export interface ValidateResult {
  /** formularz po auto-naprawie (nowy obiekt, wejście nie jest mutowane) */
  form: FormDefinition;
  rules: RuleResult[];
  repairs: Repair[];
}
/** src/validate/index.ts */
export type ValidateFn = (form: FormDefinition, opts?: { repair?: boolean }) => ValidateResult;
