const BASE = "/api/v1";
let token = "";
export const getToken = () => token;
export const setToken = (t) => { token = (t || "").trim(); };

/** Tryb demo: token prosto z /demo-config. Zwraca true, gdy token pobrany. */
export async function demoLogin() {
  try {
    const r = await fetch(`${BASE}/demo-config`);
    if (!r.ok) return false;
    const j = await r.json();
    if (j.demo && j.accessToken) { token = j.accessToken; return true; }
  } catch { /* brak backendu */ }
  return false;
}

async function call(path, init, retried = false) {
  const r = await fetch(BASE + path, { ...init, headers: { Authorization: `Bearer ${token}` } });
  if (r.status === 401 && !retried && (await demoLogin())) return call(path, init, true);
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
export function convertBatch(files, { llm }) {
  const fd = new FormData(); files.forEach((f) => fd.append("file", f));
  return call(`/forms/convert/batch?llm=${llm}`, { method: "POST", body: fd });
}
