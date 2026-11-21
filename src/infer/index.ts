/** STUB – integrator (I1). */
import type { InferFn } from '../types/stages.js';

export const infer: InferFn = (doc) => ({
  title: doc.blocks[0]?.text ?? doc.filename.replace(/\.[^.]+$/, ''),
  titleConfidence: 0.3,
  titleEvidence: [],
  tabs: [{ title: 'Dane', type: 'MAIN', fields: [], confidence: 0.3, evidence: [] }],
});
