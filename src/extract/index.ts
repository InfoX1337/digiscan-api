/** STUB – strumień EXTRACT zastępuje implementacją. */
import type { ExtractFn } from '../types/stages.js';

export const extract: ExtractFn = async ({ filename, format }) => ({
  filename,
  format,
  ocr: false,
  pages: [{ page: 1 }],
  blocks: [],
  warnings: ['extract: stub'],
});
