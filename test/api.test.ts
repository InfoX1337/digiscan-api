import { describe, it, expect, beforeAll, afterAll } from 'vitest';
import { readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';
import type { FastifyInstance } from 'fastify';
import { buildApp } from '../src/app.js';
import { loadConfig } from '../src/config.js';
import { ingest, IngestError } from '../src/ingest/index.js';

process.env.NODE_ENV = 'test';
process.env.LLM_ENABLED = 'false';
const cfg = loadConfig();
let app: FastifyInstance;
let token = '';

const MAT = new URL('./fixtures/materials/', import.meta.url).pathname;
function findMaterial(ext: string): string | undefined {
  const stack = [MAT];
  while (stack.length) {
    const d = stack.pop()!;
    let entries;
    try { entries = readdirSync(d, { withFileTypes: true }); } catch { continue; }
    for (const e of entries) {
      const p = join(d, e.name);
      if (e.isDirectory()) stack.push(p);
      else if (e.name.toLowerCase().endsWith('.' + ext) && !p.includes('Materiały do zadania')) return p;
    }
  }
  return undefined;
}

function multipart(filename: string, bytes: Buffer) {
  const boundary = '----fp' + Math.random().toString(16).slice(2);
  const head = Buffer.from(`--${boundary}\r\nContent-Disposition: form-data; name="file"; filename="${filename}"\r\nContent-Type: application/octet-stream\r\n\r\n`);
  const tail = Buffer.from(`\r\n--${boundary}--\r\n`);
  return { payload: Buffer.concat([head, bytes, tail]), headers: { 'content-type': `multipart/form-data; boundary=${boundary}` } };
}

beforeAll(async () => {
  app = await buildApp(cfg);
  const r = await app.inject({ method: 'POST', url: '/api/v1/auth/token', payload: { clientId: cfg.auth.clientId, clientSecret: cfg.auth.clientSecret } });
  token = r.json().accessToken;
});
afterAll(() => app.close());

describe('auth', () => {
  it('health bez JWT', async () => {
    const r = await app.inject({ url: '/api/v1/health' });
    expect(r.statusCode).toBe(200);
  });
  it('zły sekret = 401', async () => {
    const r = await app.inject({ method: 'POST', url: '/api/v1/auth/token', payload: { clientId: 'demo', clientSecret: 'x' } });
    expect(r.statusCode).toBe(401);
  });
  it('convert bez tokenu = 401', async () => {
    const r = await app.inject({ method: 'POST', url: '/api/v1/forms/convert' });
    expect(r.statusCode).toBe(401);
  });
  it('token wydany', () => expect(token).toMatch(/^ey/));
});

describe('ingest', () => {
  const pdf = Buffer.from('%PDF-1.4\n%âãÏÓ\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n');
  it('złe rozszerzenie', async () => {
    await expect(ingest('a.exe', pdf, 1e6)).rejects.toMatchObject({ code: 'BAD_EXTENSION' });
  });
  it('pusty', async () => {
    await expect(ingest('a.pdf', new Uint8Array(), 1e6)).rejects.toMatchObject({ code: 'EMPTY' });
  });
  it('za duży', async () => {
    await expect(ingest('a.pdf', pdf, 10)).rejects.toMatchObject({ code: 'FILE_TOO_LARGE' });
  });
  it('MIME mismatch (PDF jako .png)', async () => {
    await expect(ingest('a.png', pdf, 1e6)).rejects.toMatchObject({ code: 'MIME_MISMATCH' });
  });
  it('zła nazwa', async () => {
    await expect(ingest('../a.pdf', pdf, 1e6)).rejects.toBeInstanceOf(IngestError);
  });
  it.each(['pdf', 'png', 'jpg', 'jpeg', 'docx', 'doc', 'xlsx', 'ods'])('prawdziwy plik .%s przechodzi', async (ext) => {
    const p = findMaterial(ext);
    if (!p) return; // materiały poza repo
    const f = await ingest(p.split('/').pop(), new Uint8Array(readFileSync(p)), cfg.maxFileBytes);
    expect(f.ext).toBe(ext);
  });
});

describe('convert', () => {
  it('odrzuca plik z MIME mismatch przez API', async () => {
    const m = multipart('x.png', Buffer.from('%PDF-1.4 fake'));
    const r = await app.inject({ method: 'POST', url: '/api/v1/forms/convert', headers: { ...m.headers, authorization: `Bearer ${token}` }, payload: m.payload });
    expect(r.statusCode).toBe(415);
    expect(r.json().code).toBe('MIME_MISMATCH');
  });
});
