/**
 * Walidacja pliku wejściowego: nazwa, rozszerzenie, rozmiar, pusty plik, zgodność magic-bytes z rozszerzeniem.
 * Pliki nie są zapisywane na dysk.
 */
import { fileTypeFromBuffer } from 'file-type';
import type { SourceFormat } from '../types/source.js';
import type { ApiErrorCode } from '../types/report.js';

export class IngestError extends Error {
  constructor(
    public code: ApiErrorCode,
    message: string,
    public status = 400,
  ) {
    super(message);
  }
}

const EXT_FORMAT: Record<string, SourceFormat> = {
  pdf: 'pdf',
  png: 'image',
  jpg: 'image',
  jpeg: 'image',
  tif: 'image',
  tiff: 'image',
  docx: 'docx',
  doc: 'doc',
  xlsx: 'xlsx',
  ods: 'ods',
};

/** dopuszczalne MIME wykryte z magic-bytes dla danego rozszerzenia */
const EXT_MIME: Record<string, string[]> = {
  pdf: ['application/pdf'],
  png: ['image/png'],
  jpg: ['image/jpeg'],
  jpeg: ['image/jpeg'],
  tif: ['image/tiff'],
  tiff: ['image/tiff'],
  // DOCX/XLSX to ZIP; file-type rozpoznaje je po zawartości
  docx: ['application/vnd.openxmlformats-officedocument.wordprocessingml.document', 'application/zip'],
  xlsx: ['application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 'application/zip'],
  ods: ['application/vnd.oasis.opendocument.spreadsheet', 'application/zip'],
  // DOC = OLE2 Compound File (file-type: application/x-cfb)
  doc: ['application/x-cfb', 'application/msword'],
};

export const ALLOWED_EXTENSIONS = Object.keys(EXT_FORMAT);

export interface IngestedFile {
  filename: string;
  ext: string;
  format: SourceFormat;
  mime: string;
  bytes: Uint8Array;
}

// eslint-disable-next-line no-control-regex
const BAD_NAME = /[\u0000-\u001f<>:"|?*\\/]|^\.|\.\./;

export async function ingest(filename: string | undefined, bytes: Uint8Array, maxBytes: number): Promise<IngestedFile> {
  const name = (filename ?? '').normalize('NFC').trim();
  if (!name || name.length > 255 || BAD_NAME.test(name)) {
    throw new IngestError('BAD_FILENAME', 'Niepoprawna nazwa pliku.');
  }
  const dot = name.lastIndexOf('.');
  const ext = dot > 0 ? name.slice(dot + 1).toLowerCase() : '';
  const format = EXT_FORMAT[ext];
  if (!format) {
    throw new IngestError('BAD_EXTENSION', `Nieobsługiwane rozszerzenie ".${ext}". Dozwolone: ${ALLOWED_EXTENSIONS.join(', ')}.`, 415);
  }
  if (bytes.byteLength === 0) throw new IngestError('EMPTY', 'Plik jest pusty.');
  if (bytes.byteLength > maxBytes) {
    throw new IngestError('FILE_TOO_LARGE', `Plik przekracza limit ${Math.round(maxBytes / 1024 / 1024)} MB.`, 413);
  }
  const detected = await fileTypeFromBuffer(bytes);
  const mime = detected?.mime ?? 'unknown';
  if (!EXT_MIME[ext]!.includes(mime)) {
    throw new IngestError('MIME_MISMATCH', `Zawartość pliku (${mime}) nie pasuje do rozszerzenia ".${ext}".`, 415);
  }
  return { filename: name, ext, format, mime, bytes };
}
