/**
 * SourceDoc – znormalizowany wynik ekstrakcji z dowolnego formatu (PDF, obraz/OCR, DOCX, DOC, XLSX, ODS).
 * Kontrakt: EXTRACT (out) → INFER (in). Kolejność `blocks` = kolejność czytania.
 */

export type SourceFormat = 'pdf' | 'image' | 'docx' | 'doc' | 'xlsx' | 'ods';

/** Współrzędne w jednostkach strony (PDF: pt, obraz: px), początek lewy górny róg. */
export interface BBox {
  x: number;
  y: number;
  w: number;
  h: number;
}

export type BlockKind =
  /** akapit / linia tekstu */
  | 'text'
  /** komórka tabeli (DOCX/XLSX/ODS lub wykryta siatka) */
  | 'cell'
  /** pole wyboru ☐/☑/□/■ z etykietą w `text` */
  | 'checkbox'
  /** linia do wypełnienia (….., ____, pusta komórka obok etykiety) */
  | 'line';

export interface BlockStyle {
  bold?: boolean;
  italic?: boolean;
  /** pt (PDF/DOCX) lub wysokość px (OCR) */
  fontSize?: number;
  /** nagłówek wg stylu źródła (Heading1 → 1) */
  heading?: number;
  /** wyrównanie do środka (tytuły) */
  centered?: boolean;
}

export interface SourceBlock {
  /** stabilne w obrębie dokumentu, np. "p1-b12" */
  id: string;
  /** numer strony / arkusza, od 1 */
  page: number;
  kind: BlockKind;
  text: string;
  bbox?: BBox;
  style?: BlockStyle;
  /** dla `cell`: identyfikator tabeli, wiersz, kolumna (od 0), rozpiętości */
  table?: number;
  row?: number;
  col?: number;
  rowSpan?: number;
  colSpan?: number;
  /** dla `checkbox`: czy zaznaczony w źródle */
  checked?: boolean;
  /** pewność ekstrakcji 0..1 (OCR: confidence tesseract/100; tekst natywny: 1) */
  confidence?: number;
}

export interface SourcePage {
  page: number;
  width?: number;
  height?: number;
  /** arkusz XLSX/ODS */
  name?: string;
}

export interface SourceDoc {
  filename: string;
  format: SourceFormat;
  /** true, jeśli tekst pochodzi z OCR */
  ocr: boolean;
  pages: SourcePage[];
  blocks: SourceBlock[];
  /** ostrzeżenia ekstrakcji (np. "DOC: brak układu, tylko tekst") */
  warnings: string[];
}
