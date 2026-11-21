import Fastify from 'fastify';
import multipart from '@fastify/multipart';
import swagger from '@fastify/swagger';
import swaggerUi from '@fastify/swagger-ui';
import fastifyStatic from '@fastify/static';
import { existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';
import type { Config } from './config.js';
import { registerAuth } from './auth/index.js';
import { registerRoutes } from './routes/index.js';

export async function buildApp(cfg: Config) {
  const app = Fastify({
    logger: cfg.env === 'test' ? false : { level: cfg.logLevel, redact: ['req.headers.authorization'] },
    bodyLimit: cfg.maxFileBytes * 2,
    requestTimeout: cfg.requestTimeoutMs + 5000,
  });

  await app.register(swagger, {
    openapi: {
      info: { title: 'FormProof API', version: '0.1.0', description: 'Konwersja formularzy (PDF/obraz/DOCX/DOC/XLSX/ODS) do JSON kreatora eUsług COI.' },
      components: { securitySchemes: { bearer: { type: 'http', scheme: 'bearer', bearerFormat: 'JWT' } } },
      security: [{ bearer: [] }],
    },
  });
  await app.register(swaggerUi, { routePrefix: '/docs' });
  await app.register(multipart, {
    limits: { fileSize: cfg.maxFileBytes, files: cfg.maxBatchFiles + 1, fields: 10, parts: cfg.maxBatchFiles + 11 },
    throwFileSizeLimit: true,
  });
  await registerAuth(app, cfg);
  await registerRoutes(app, cfg);

  app.get('/api/v1/demo-config', { schema: { hide: true } }, async () =>
    cfg.demoUi ? { demo: true, clientId: cfg.auth.clientId, clientSecret: cfg.auth.clientSecret } : { demo: false },
  );

  const webDist = join(fileURLToPath(new URL('.', import.meta.url)), '..', 'web', 'dist');
  if (existsSync(webDist)) {
    await app.register(fastifyStatic, { root: webDist, prefix: '/' });
  }
  return app;
}
