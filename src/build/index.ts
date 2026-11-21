/** STUB – integrator (I2). */
import { randomUUID } from 'node:crypto';
import type { BuildFn } from '../types/stages.js';

export const build: BuildFn = (draft) => ({
  form: {
    title: draft.title,
    tabs: draft.tabs.map((t) => ({ id: randomUUID(), title: t.title, type: t.type, questions: [] })),
    flow: { links: [] },
  },
  keyToId: {},
});
