import type { FastifyInstance, FastifyReply, FastifyRequest } from 'fastify';
import type { Config } from '../config.js';
import { ingest, IngestError } from '../ingest/index.js';
import { convert } from '../pipeline.js';
import { validate } from '../validate/index.js';
import { getDictionary, listDictionaries } from '../dict/index.js';
import type { ApiError, BatchResult } from '../types/report.js';
import type { FormDefinition } from '../types/form.js';

function sendError(reply: FastifyReply, err: unknown) {
  if (err instanceof IngestError) {
    return reply.code(err.status).send({ code: err.code, message: err.message } satisfies ApiError);
  }
  if (err instanceof Error && err.name === 'AbortError') {
    return reply.code(504).send({ code: 'TIMEOUT', message: 'Przekroczono czas przetwarzania.' } satisfies ApiError);
  }
  reply.log.error({ err }, 'convert failed');
  return reply.code(500).send({ code: 'INTERNAL', message: 'Błąd przetwarzania pliku.' } satisfies ApiError);
}

function toApiError(err: unknown): ApiError {
  if (err instanceof IngestError) return { code: err.code, message: err.message };
  if (err instanceof Error && err.name === 'AbortError') return { code: 'TIMEOUT', message: 'Przekroczono czas przetwarzania.' };
  return { code: 'INTERNAL', message: 'Błąd przetwarzania pliku.' };
}

const convertQuery = {
  type: 'object',
  properties: {
    llm: { type: 'boolean', default: true },
  },
} as const;

export async function registerRoutes(app: FastifyInstance, cfg: Config) {
  const auth = { onRequest: [app.authenticate] };

  app.get('/api/v1/health', { schema: { tags: ['system'] } }, async () => ({
    status: 'ok',
    llm: { enabled: cfg.llm.enabled, model: cfg.llm.model },
  }));

  app.post(
    '/api/v1/forms/convert',
    { ...auth, schema: { tags: ['forms'], consumes: ['multipart/form-data'], querystring: convertQuery } },
    async (req: FastifyRequest<{ Querystring: { llm: boolean } }>, reply) => {
      const signal = AbortSignal.timeout(cfg.requestTimeoutMs);
      try {
        const part = await req.file();
        if (!part) throw new IngestError('NO_FILE', 'Brak pliku w polu "file".');
        const bytes = new Uint8Array(await part.toBuffer());
        const file = await ingest(part.filename, bytes, cfg.maxFileBytes);
        return await convert(file, cfg, { llm: req.query.llm, signal });
      } catch (err) {
        if ((err as { code?: string }).code === 'FST_REQ_FILE_TOO_LARGE') {
          return sendError(reply, new IngestError('FILE_TOO_LARGE', 'Plik przekracza limit rozmiaru.', 413));
        }
        return sendError(reply, err);
      }
    },
  );

  app.post(
    '/api/v1/forms/convert/batch',
    { ...auth, schema: { tags: ['forms'], consumes: ['multipart/form-data'], querystring: convertQuery } },
    async (req: FastifyRequest<{ Querystring: { llm: boolean } }>, reply) => {
      const results: BatchResult[] = [];
      try {
        for await (const part of req.files()) {
          if (results.length >= cfg.maxBatchFiles) {
            throw new IngestError('TOO_MANY_FILES', `Maksymalnie ${cfg.maxBatchFiles} plików w jednym żądaniu.`);
          }
          const filename = part.filename ?? '';
          try {
            const bytes = new Uint8Array(await part.toBuffer());
            const file = await ingest(filename, bytes, cfg.maxFileBytes);
            const r = await convert(file, cfg, { llm: req.query.llm, signal: AbortSignal.timeout(cfg.requestTimeoutMs) });
            results.push({ filename, ok: true, ...r });
          } catch (err) {
            results.push({ filename, ok: false, error: toApiError(err) });
          }
        }
        if (!results.length) throw new IngestError('NO_FILE', 'Brak plików w polu "file".');
        return { results };
      } catch (err) {
        return sendError(reply, err);
      }
    },
  );

  app.post(
    '/api/v1/forms/validate',
    { ...auth, schema: { tags: ['forms'], body: { type: 'object', required: ['title', 'tabs'] } } },
    async (req: FastifyRequest<{ Body: FormDefinition; Querystring: { repair?: string } }>, reply) => {
      try {
        return validate(req.body, { repair: req.query.repair !== 'false' });
      } catch (err) {
        return reply.code(422).send({ code: 'INVALID_FORM', message: (err as Error).message } satisfies ApiError);
      }
    },
  );

  app.get('/api/v1/dictionaries', { ...auth, schema: { tags: ['dictionaries'] } }, async () => ({
    dictionaries: listDictionaries(),
  }));

  app.get(
    '/api/v1/dictionaries/:name',
    { ...auth, schema: { tags: ['dictionaries'] } },
    async (req: FastifyRequest<{ Params: { name: string } }>, reply) => {
      const items = getDictionary(req.params.name);
      if (!items) return reply.code(404).send({ code: 'NOT_FOUND', message: 'Nieznany słownik.' });
      return { name: req.params.name, items };
    },
  );
}
