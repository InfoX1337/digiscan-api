export function h(tag, attrs = {}, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === "class") e.className = v;
    else if (k === "text") e.textContent = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else if (k === "style" && typeof v === "object") Object.assign(e.style, v);
    else e.setAttribute(k, v === true ? "" : v);
  }
  for (const c of kids.flat()) if (c != null && c !== false) e.append(c.nodeType ? c : document.createTextNode(String(c)));
  return e;
}
export const $ = (s, r = document) => r.querySelector(s);
export const $$ = (s, r = document) => [...r.querySelectorAll(s)];
export const pct = (v) => Math.round(v * 100) + "%";
export function confClass(c) { return c >= 0.85 ? "hi" : c >= 0.6 ? "mid" : "lo"; }
export function confLabel(c) { return c >= 0.85 ? "wysoka" : c >= 0.6 ? "średnia" : "niska"; }

/** Bezpieczne renderowanie description (HTML z materiałów COI): whitelist znaczników. */
const ALLOWED = new Set(["P", "BR", "B", "STRONG", "I", "EM", "U", "UL", "OL", "LI", "SPAN", "A", "H1", "H2", "H3", "H4", "DIV", "SUB", "SUP"]);
export function safeHtml(html) {
  const doc = new DOMParser().parseFromString(html || "", "text/html");
  const out = document.createDocumentFragment();
  const walk = (node, into) => {
    for (const n of [...node.childNodes]) {
      if (n.nodeType === 3) into.append(document.createTextNode(n.textContent));
      else if (n.nodeType === 1) {
        if (!ALLOWED.has(n.tagName)) { walk(n, into); continue; }
        const c = document.createElement(n.tagName);
        if (n.tagName === "A") { c.setAttribute("rel", "noreferrer"); c.setAttribute("target", "_blank"); }
        walk(n, c); into.append(c);
      }
    }
  };
  walk(doc.body, out);
  return out;
}
export const hasText = (html) => !!(new DOMParser().parseFromString(html || "", "text/html").body.textContent || "").trim();

export function highlightJson(obj) {
  const s = JSON.stringify(obj, null, 2).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  return s.replace(/("(?:\\.|[^"\\])*")(\s*:)?|\b(true|false)\b|\bnull\b|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?/g, (m, str, colon, bool) => {
    if (str) return colon ? `<span class="j-k">${str}</span>${colon}` : `<span class="j-s">${str}</span>`;
    if (bool) return `<span class="j-b">${m}</span>`;
    if (m === "null") return `<span class="j-n">${m}</span>`;
    return `<span class="j-d">${m}</span>`;
  });
}
export function download(name, text, type = "application/json") {
  const a = h("a", { href: URL.createObjectURL(new Blob([text], { type })), download: name });
  document.body.append(a); a.click(); a.remove();
}
