/**
 * DraftForm – pośrednia reprezentacja (INFER/LLM/DICT → BUILD).
 * Bez UUID i siatki; z pewnością i źródłem każdej decyzji.
 */
import type { FieldType, Validator, FieldState, ConsentSectionConfig } from './form.js';

export interface Evidence {
  /** id bloków SourceDoc, z których wynika decyzja */
  blockIds: string[];
  /** kto zdecydował */
  by: 'rules' | 'llm' | 'dict' | 'repair';
  /** krótkie uzasadnienie po polsku, np. "etykieta zawiera 'PESEL'" */
  reason?: string;
}

export interface DraftOption {
  name: string;
  checked?: boolean;
}

export interface DraftField {
  /** tymczasowy klucz w drafcie (np. "f12"); BUILD nadaje UUID i techName */
  key: string;
  type: FieldType;
  title: string;
  description?: string;
  tooltipMessage?: string;
  options?: DraftOption[];
  validation: Validator[];
  readOnly?: boolean;
  dictionaryName?: string;
  multiLevelTree?: boolean;
  defaultValue?: string | string[];
  defaultValueType?: 'EXTERNAL_SYSTEM';
  consentSectionConfig?: ConsentSectionConfig;
  /** dzieci dla SECTION / REPEATING_SECTION */
  children?: DraftField[];
  /** zależność: pokaż gdy pole `whenKey` ma wartość `equals` (BUILD → JSONata) */
  showWhen?: { whenKey: string; equals: string; negate?: boolean }[];
  /** gotowe stany (np. z LLM), BUILD przepisuje 1:1 */
  states?: FieldState[];
  /** sugerowana szerokość 1..3 kolumn */
  width?: 1 | 2 | 3;
  /** 0..1 */
  confidence: number;
  evidence: Evidence[];
}

export interface DraftTab {
  title: string;
  type: 'MAIN' | 'FINISH';
  fields: DraftField[];
  confidence: number;
  evidence: Evidence[];
}

export interface DraftForm {
  title: string;
  titleConfidence: number;
  titleEvidence: Evidence[];
  tabs: DraftTab[];
}
