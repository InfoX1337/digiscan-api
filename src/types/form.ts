/**
 * FormDefinition – JSON importowany do kreatora eUsług COI.
 * Źródło: materiały COI (importowanyPlikJsonSchemat.json + OpisImportowanegoPlikuJSON + example1).
 * Uwaga: schema ma literówkę `repetingSectionGrid`; przykłady COI używają `repeatingSectionGrid` – emitujemy tę drugą.
 */

export const FIELD_TYPES = [
  'SECTION',
  'REPEATING_SECTION',
  'TEXT_FIELD',
  'TEXTAREA',
  'NUMBER',
  'DATEPICKER',
  'SELECT',
  'RADIO',
  'CHECKBOX',
  'FILE_UPLOADER',
  'CONSENT_SECTION',
  'TEXT_BLOCK',
  'INFO_SECTION',
] as const;
export type FieldType = (typeof FIELD_TYPES)[number];

/** Typy-kontenery (mają repeatingSectionGrid z dziećmi). */
export const CONTAINER_TYPES: readonly FieldType[] = ['SECTION', 'REPEATING_SECTION'];
/** Typy prezentacyjne (bez odpowiedzi użytkownika). */
export const PRESENTATIONAL_TYPES: readonly FieldType[] = ['TEXT_BLOCK', 'INFO_SECTION'];

export const VALIDATORS = [
  'REQUIRED',
  'EMAIL',
  'PESEL',
  'NIP',
  'REGON',
  'ZIP_CODE',
  'EPUAP',
  'ADE',
  'SERIAL_NUMBER_ID_CARD',
] as const;
export type Validator = (typeof VALIDATORS)[number];

export type TabType = 'MAIN' | 'FINISH';
export type StateType = 'SHOW' | 'HIDE' | 'READ_ONLY' | 'REQUIRED' | (string & {});

export interface FieldOption {
  id: string;
  name: string;
  techName: string;
}

export interface FieldState {
  type: StateType;
  /** Wyrażenie JSONata. */
  query: string;
}

export interface ConsentSectionConfig {
  consents: { description: string }[];
  required: boolean;
  files: unknown[];
}

export interface Field {
  id: string;
  type: FieldType;
  techName: string;
  title: string;
  description: string;
  options: FieldOption[];
  validation: Validator[];
  readOnly: boolean;
  repeatingSectionGrid: Question[];
  states: FieldState[];
  questionOrder: number;
  tooltipMessage: string;
  dictionaryName?: string;
  multiLevelTree?: boolean;
  searchEnabled?: boolean;
  /** string lub tablica (SELECT z domyślną wartością, np. ["Polska"]). */
  defaultValue?: string | string[];
  defaultValueType?: 'EXTERNAL_SYSTEM' | '';
  consentSectionConfig?: ConsentSectionConfig;
}

/** Pozycja w siatce: CSS grid-area: {y+1} / {x+1} / span {rows} / span {cols}. */
export interface Question {
  x: number;
  y: number;
  rows: number;
  cols: number;
  field: Field;
}

export interface Tab {
  id: string;
  title: string;
  type: TabType;
  questions: Question[];
}

export interface FlowLink {
  id: string;
  source: string;
  target: string;
}

export interface FormDefinition {
  title: string;
  tabs: Tab[];
  flow: { links: FlowLink[] };
}

/** Szerokość siatki w kreatorze COI (przykłady używają cols 1..3). */
export const GRID_COLS = 3;
