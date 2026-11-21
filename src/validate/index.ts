/** STUB – strumień VALIDATE zastępuje implementacją. */
import type { ValidateFn } from '../types/stages.js';

export const validate: ValidateFn = (form) => ({ form: structuredClone(form), rules: [], repairs: [] });
