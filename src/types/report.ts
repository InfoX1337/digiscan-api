/**
 * Report – dowód i zaufanie (wyróżnik FormProof). Zwracany obok czystego `form`.
 */
import type { BBox, SourceFormat } from './source.js';
import type { FormDefinition } from './form.js';

export interface SourceRef {
  page: number;
  bbox?: BBox;
  text: string;
  blockIds: string[];
}

export interface FieldReport {
  /** UUID pola w `form` */
  id: string;
  techName: string;
  title: string;
  type: string;
  /** 0..1 */
  confidence: number;
  /** skąd pole pochodzi w oryginale (puste dla pól dodanych przez auto-naprawę) */
  sources: SourceRef[];
  decidedBy: ('rules' | 'llm' | 'dict' | 'repair')[];
  reasons: string[];
}

export type RuleSeverity = 'error' | 'warning' | 'info';

export interface RuleResult {
  /** stabilny id reguły, np. "COI-TAB-FINISH" */
  id: string;
  /** opis po polsku (z materiałów COI) */
  title: string;
  severity: RuleSeverity;
  passed: boolean;
  /** po auto-naprawie */
  repaired: boolean;
  /** UUID/techName pól, których dotyczy */
  targets: string[];
  message?: string;
}

export interface Repair {
  ruleId: string;
  /** ścieżka JSON Pointer w `form` */
  path: string;
  description: string;
  before?: unknown;
  after?: unknown;
}

export interface ReviewItem {
  /** UUID pola */
  fieldId: string;
  techName: string;
  title: string;
  confidence: number;
  reason: string;
}

export interface ProposedDictionary {
  name: string;
  /** pole (UUID), z którego wyprowadzono propozycję */
  fieldId: string;
  items: string[];
  reason: string;
}

export interface Report {
  filename: string;
  format: SourceFormat;
  ocr: boolean;
  /** średnia ważona pewność całego formularza 0..1 */
  confidence: number;
  fields: Record<string, FieldReport>;
  review: ReviewItem[];
  rules: RuleResult[];
  repairs: Repair[];
  proposedDictionaries: ProposedDictionary[];
  warnings: string[];
  timings: Record<string, number>;
  llm: { used: boolean; model?: string; error?: string };
}

export interface ConvertResponse {
  form: FormDefinition;
  report: Report;
}

export interface ValidateResponse {
  /** formularz po auto-naprawie */
  form: FormDefinition;
  rules: RuleResult[];
  repairs: Repair[];
}

export interface BatchResult {
  filename: string;
  ok: boolean;
  form?: FormDefinition;
  report?: Report;
  error?: ApiError;
}

export interface BatchResponse {
  results: BatchResult[];
}

export type ApiErrorCode =
  | 'FILE_TOO_LARGE'
  | 'BAD_EXTENSION'
  | 'MIME_MISMATCH'
  | 'BAD_FILENAME'
  | 'EMPTY'
  | 'NO_FILE'
  | 'TOO_MANY_FILES'
  | 'UNAUTHORIZED'
  | 'NOTHING_EXTRACTED'
  | 'TIMEOUT'
  | 'INVALID_FORM'
  | 'INTERNAL';

export interface ApiError {
  code: ApiErrorCode;
  message: string;
}
