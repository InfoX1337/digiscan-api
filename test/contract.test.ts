import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import type { FormDefinition, Question } from '../src/types/form.js';
import { FIELD_TYPES } from '../src/types/form.js';
import type { SourceDoc } from '../src/types/source.js';
import type { ConvertResponse } from '../src/types/report.js';

const load = <T>(p: string): T => JSON.parse(readFileSync(new URL(p, import.meta.url), 'utf8')) as T;

function* walk(qs: Question[]): Generator<Question> {
  for (const q of qs) { yield q; yield* walk(q.field.repeatingSectionGrid ?? []); }
}

describe('fixtures zgodne z kontraktem', () => {
  it('expected1 używa tylko znanych typów pól', () => {
    const f = load<FormDefinition>('./fixtures/expected1.json');
    for (const t of f.tabs) for (const q of walk(t.questions)) expect(FIELD_TYPES).toContain(q.field.type);
  });
  it('sample-source ma bloki z bbox', () => {
    const s = load<SourceDoc>('./fixtures/sample-source.json');
    expect(s.blocks.length).toBeGreaterThan(20);
    expect(s.blocks.every((b) => b.bbox && b.page >= 1)).toBe(true);
  });
  it('sample-response ma form i report', () => {
    const r = load<ConvertResponse>('./fixtures/sample-response.json');
    expect(r.form.tabs.length).toBeGreaterThan(0);
    expect(Object.keys(r.report.fields).length).toBeGreaterThan(0);
  });
});
