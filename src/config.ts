/** Konfiguracja wyłącznie z env (parametry integracyjne w jednym miejscu). */

function str(name: string, def: string): string {
  const v = process.env[name];
  return v === undefined || v === '' ? def : v;
}
function int(name: string, def: number): number {
  const v = process.env[name];
  if (v === undefined || v === '') return def;
  const n = Number.parseInt(v, 10);
  if (!Number.isFinite(n) || n < 0) throw new Error(`Config: ${name} musi być liczbą >= 0`);
  return n;
}
function bool(name: string, def: boolean): boolean {
  const v = process.env[name];
  if (v === undefined || v === '') return def;
  return v === '1' || v.toLowerCase() === 'true';
}

export function loadConfig() {
  const env = str('NODE_ENV', 'development');
  const jwtSecret = str('JWT_SECRET', env === 'production' ? '' : 'dev-secret-change-me-dev-secret-change-me');
  if (jwtSecret.length < 32) throw new Error('Config: JWT_SECRET musi mieć >= 32 znaki');
  return {
    env,
    port: int('PORT', 3000),
    host: str('HOST', '0.0.0.0'),
    logLevel: str('LOG_LEVEL', 'info'),
    maxFileBytes: int('MAX_FILE_BYTES', 15 * 1024 * 1024),
    maxBatchFiles: int('MAX_BATCH_FILES', 10),
    maxOcrPages: int('MAX_OCR_PAGES', 5),
    requestTimeoutMs: int('REQUEST_TIMEOUT_MS', 120_000),
    jwt: {
      secret: jwtSecret,
      expiresIn: str('JWT_EXPIRES_IN', '1h'),
      issuer: str('JWT_ISSUER', 'formproof'),
      audience: str('JWT_AUDIENCE', 'formproof-api'),
    },
    auth: {
      clientId: str('AUTH_CLIENT_ID', 'demo'),
      clientSecret: str('AUTH_CLIENT_SECRET', 'demo-secret'),
    },
    llm: {
      enabled: bool('LLM_ENABLED', true),
      url: str('OLLAMA_URL', 'http://localhost:11434'),
      model: str('LLM_MODEL', 'qwen3.5:4b'),
      timeoutMs: int('LLM_TIMEOUT_MS', 45_000),
    },
    /** UI: tryb demo pobiera token automatycznie */
    demoUi: bool('DEMO_UI', true),
  } as const;
}

export type Config = ReturnType<typeof loadConfig>;
