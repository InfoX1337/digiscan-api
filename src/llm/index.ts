/** STUB – runda 2 (LLM). Nigdy nie rzuca. */
import type { EnrichFn } from '../types/stages.js';

export const enrich: EnrichFn = async (_doc, draft) => ({ draft, used: false });
