const BASE = "/api/v1";
let token = "";
export const getToken = () => token;
export const setToken = (t) => { token = (t || "").trim(); };

export let authRequired = true;

/** Tryb demo: API otwarte (authRequired=false) albo token z /demo-config. Zwraca true, gdy można działać. */
export async function demoLogin() {
  try {
    const r = await fetch(`${BASE}/demo-config`);
    if (!r.ok) return false;
    const j = await r.json();
    authRequired = j.authRequired !== false;
    if (!authRequired) return true;
    if (j.demo && j.accessToken) { token = j.accessToken; return true; }
  } catch { /* brak backendu */ }
  return false;
}

async function call(path, init, retried = false) {
  const r = await fetch(BASE + path, { ...init, headers: { ...init?.headers, ...(token ? { Authorization: `Bearer ${token}` } : {}) } });
  if (r.status === 401 && authRequired && !retried && (await demoLogin())) return call(path, init, true);
  const body = await r.json().catch(() => ({}));
  if (!r.ok) {
    const e = new Error(body.message || `Błąd HTTP ${r.status}`);
    e.code = body.code || String(r.status); e.status = r.status;
    throw e;
  }
  return body;
}

export function convert(file, { llm, previews }) {
  const fd = new FormData(); fd.append("file", file);
  return call(`/forms/convert?llm=${llm}&previews=${previews}`, { method: "POST", body: fd });
}
/** Konwersja z postępem: onStage({stage, status, ms}) przy starcie/końcu etapów (strumień NDJSON). */
export async function convertStream(file, { llm, previews }, onStage, retried = false) {
  const fd = new FormData(); fd.append("file", file);
  const r = await fetch(`${BASE}/forms/convert?llm=${llm}&previews=${previews}&stream=true`, {
    method: "POST", body: fd, headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (r.status === 401 && authRequired && !retried && (await demoLogin())) return convertStream(file, { llm, previews }, onStage, true);
  if (!r.ok || !r.body) {
    const body = await r.json().catch(() => ({}));
    const e = new Error(body.message || `Błąd HTTP ${r.status}`);
    e.code = body.code || String(r.status); e.status = r.status;
    throw e;
  }
  const reader = r.body.pipeThrough(new TextDecoderStream()).getReader();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += value;
    let nl;
    while ((nl = buf.indexOf("\n")) >= 0) {
      const line = buf.slice(0, nl).trim(); buf = buf.slice(nl + 1);
      if (!line) continue;
      const msg = JSON.parse(line);
      if (msg.stage) onStage(msg);
      else if (msg.result) return msg.result;
      else if (msg.error) {
        const e = new Error(msg.error.message); e.code = msg.error.code; e.status = msg.error.status;
        throw e;
      }
    }
  }
  throw new Error("Połączenie przerwane przed końcem przetwarzania.");
}
export function convertBatch(files, { llm }) {
  const fd = new FormData(); files.forEach((f) => fd.append("file", f));
  return call(`/forms/convert/batch?llm=${llm}`, { method: "POST", body: fd });
}
export function validate(form) {
  return call("/forms/validate?repair=true", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(form) });
}
