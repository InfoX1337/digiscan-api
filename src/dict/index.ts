/** STUB – runda 2 (DICT). */
import type { DictFn } from '../types/stages.js';

export const applyDictionaries: DictFn = (draft) => ({ draft, proposed: [] });
export function listDictionaries(): { name: string; size: number }[] {
  return [];
}
export function getDictionary(_name: string): string[] | undefined {
  return undefined;
}
