import { h, pct, confClass, confLabel, highlightJson, download } from "./util.js";
import { typeLabel, TYPE_PL_EDIT } from "./viz.js";

const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;

const short = (v) => { const s = typeof v === "string" ? v : JSON.stringify(v); return s == null ? "—" : s.length > 80 ? s.slice(0, 77) + "…" : s; };

export function renderRules(root, report) {
  const rules = report.rules || [];
  const ok = rules.filter((r) => r.passed).length;
  const repaired = rules.filter((r) => r.repaired).length;
  const nRep = (report.repairs || []).length;
  const bad = rules.filter((r) => !r.passed);
  const errs = bad.filter((r) => r.severity === "error").length;
  const state = errs ? "fail" : bad.length ? "warn" : "ok";
  const okEl = h("span", {}, "0");
  const verdict = { ok: "Zgodny z regułami COI", warn: "Zgodny, z uwagami", fail: "Błędy zgodności" }[state];

  const chips = rules.map((r) => {
    const st = r.passed ? (r.repaired ? "fixed" : "ok") : r.severity === "error" ? "fail" : "warn";
    const lbl = { ok: "OK", fixed: "naprawiono", fail: "błąd", warn: "ostrzeżenie" }[st];
    const ico = { ok: "✓", fixed: "✎", fail: "✕", warn: "!" }[st];
    return h("li", { class: `rule ${st}`, "data-testid": `rule-${r.id}`, "data-status": st },
      h("span", { class: "ico", "aria-hidden": "true" }, ico),
      h("div", {}, h("div", { class: "rule-t" }, r.title), h("div", { class: "rule-s" }, h("code", {}, r.id), " · ", lbl, r.message ? ` · ${r.message}` : "")));
  });

  const reps = (report.repairs || []).map((p) =>
    h("li", {}, h("div", { class: "rep-d" }, h("code", {}, p.ruleId), " ", p.description),
      h("div", { class: "rep-p" }, p.path),
      p.before !== undefined || p.after !== undefined
        ? h("div", { class: "ba" }, h("span", { class: "before" }, short(p.before)), h("span", { class: "arrow", "aria-hidden": "true" }, "→"), h("span", { class: "after" }, short(p.after)))
        : null));

  const nFields = Object.keys(report.fields || {}).length;
  const nReview = (report.review || []).length;
  const notOk = chips.filter((c) => c.dataset.status !== "ok");
  const okChips = chips.filter((c) => c.dataset.status === "ok");
  const ico = h("span", { class: "verdict-ico", "aria-hidden": "true" });
  ico.innerHTML = `<svg class="i" viewBox="0 0 24 24">${{ ok: '<path d="M5 12.5l4.5 4.5L19 7.5"/>', warn: '<path d="M12 7v6M12 17h.01"/>', fail: '<path d="M7 7l10 10M17 7L7 17"/>' }[state]}</svg>`;
  const stat = (label, value, cls = "", extra = null) => h("div", { class: `stat ${cls}` }, h("dt", {}, label), h("dd", {}, value, extra));
  const sub = [repaired ? `${repaired} ${plural(repaired, "reguła naprawiona", "reguły naprawione", "reguł naprawionych")} automatycznie` : null,
    bad.length ? `${bad.length} ${plural(bad.length, "uwaga", "uwagi", "uwag")}` : null].filter(Boolean).join(" · ") || "Bez uwag";

  root.replaceChildren(...[h("div", { class: `rules-hero ${state}` },
    h("div", { class: "verdict" }, ico, h("div", {}, h("h2", {}, verdict), h("p", {}, sub))),
    h("dl", { class: "stats" },
      stat("Reguły COI", okEl, state, h("small", { class: "muted" }, `/${rules.length}`)),
      stat("Auto-naprawy", String(nRep), nRep ? "fixed" : ""),
      stat("Do przeglądu", String(nReview), nReview ? "warn" : ""),
      stat("Pola z dowodem", String(nFields)))),
    notOk.length ? h("ul", { class: "rule-grid" }, notOk) : null,
    h("details", { class: "rules-ok", "data-testid": "rules-ok" },
      h("summary", {}, `Spełnione reguły (${okChips.length})`),
      h("ul", { class: "rule-grid" }, okChips)),
    h("details", { class: "repairs", open: nRep > 0 },
      h("summary", {}, `Wykonane auto-naprawy (${nRep})`),
      nRep ? h("ol", { "data-testid": "repairs-list", class: "repairs-list" }, reps) : h("p", { class: "muted", "data-testid": "repairs-list" }, "Brak napraw."))].filter(Boolean));
  okEl.textContent = ok;
}

export function plural(n, one, few, many) {
  const m10 = n % 10, m100 = n % 100;
  return n === 1 ? one : m10 >= 2 && m10 <= 4 && !(m100 >= 12 && m100 <= 14) ? few : many;
}

export function renderReview(root, report, onSelect) {
  const items = [...(report.review || [])].sort((a, b) => a.confidence - b.confidence);
  root.replaceChildren(
    h("p", { class: "muted" }, items.length ? `${items.length} ${plural(items.length, "pole", "pola", "pól")} do weryfikacji, od najmniej pewnych.` : "Brak pól wymagających przeglądu."),
    h("ul", { "data-testid": "review-list", class: "review-list" }, items.map((it) =>
      h("li", {}, h("button", { class: "review-item", "data-testid": "review-item", "data-field-id": it.fieldId, onclick: () => onSelect(it.fieldId) },
        h("span", { class: `conf ${confClass(it.confidence)}` }, pct(it.confidence)),
        h("span", { class: "ri-t" }, it.title || it.techName, h("small", {}, it.reason)))))));
}

export function renderJson(root, form) {
  const text = JSON.stringify(form, null, 2);
  const pre = h("pre", { "data-testid": "json-view", class: "json" });
  pre.innerHTML = highlightJson(form);
  const copy = h("button", { class: "btn small", onclick: async () => { try { await navigator.clipboard.writeText(text); copy.textContent = "Skopiowano"; setTimeout(() => (copy.textContent = "Kopiuj"), 1500); } catch { /* brak schowka */ } } }, "Kopiuj");
  root.replaceChildren(h("div", { class: "json-bar" }, h("span", { class: "muted" }, `${(text.length / 1024).toFixed(1)} kB`), copy), pre);
}

export function renderReport(root, report) {
  const t = report.timings || {};
  const row = (k, v) => h("tr", {}, h("th", {}, k), h("td", {}, v));
  root.replaceChildren(
    h("table", { class: "kv" },
      row("Plik", report.filename), row("Format", `${report.format}${report.ocr ? " (OCR)" : ""}`),
      row("Pewność łączna", pct(report.confidence)),
      row("LLM", report.llm?.used ? `użyty (${report.llm.model})` : `nieużyty${report.llm?.error ? `: ${report.llm.error}` : ""}`)),
    h("h4", {}, "Czasy etapów"),
    h("table", { class: "kv", "data-testid": "timings" }, Object.entries(t).map(([k, v]) => row(k, `${v} ms`))),
    (report.warnings || []).length ? h("div", {}, h("h4", {}, "Ostrzeżenia"), h("ul", {}, report.warnings.map((w) => h("li", {}, w)))) : null,
    (report.proposedDictionaries || []).length ? h("div", {}, h("h4", {}, "Proponowane słowniki"),
      report.proposedDictionaries.map((d) => h("div", { class: "dict" }, h("strong", {}, d.name), h("div", { class: "muted" }, d.reason), h("div", {}, d.items.map((i) => h("span", { class: "chip" }, i)))))) : null);
}

export function renderDetails(root, f, fr, onApply) {
  if (!f) { root.replaceChildren(h("p", { class: "muted" }, "Wybierz pole, aby zobaczyć źródło, pewność i powody decyzji.")); return; }
  const dec = { rules: "reguły", human: "urzędnik", llm: "model językowy", dict: "słownik", repair: "auto-naprawa" };
  const edit = f && onApply ? editForm(f, onApply) : null;
  root.replaceChildren(
    h("h3", {}, f.title), h("p", { class: "muted" }, `${typeLabel(f.type)} · `, h("code", {}, f.techName)),
    fr ? h("div", { class: `conf-big ${confClass(fr.confidence)}` }, h("b", {}, pct(fr.confidence)), ` pewność ${confLabel(fr.confidence)}`) : h("p", { class: "muted" }, "Brak danych report dla tego pola."),
    fr?.decidedBy?.length ? h("p", {}, "Zdecydowali: ", fr.decidedBy.map((d) => h("span", { class: "chip" }, dec[d] || d))) : null,
    fr?.reasons?.length ? h("div", {}, h("h4", {}, "Powody"), h("ul", {}, fr.reasons.map((r) => h("li", {}, r)))) : null,
    h("h4", {}, "Tekst źródłowy"),
    fr?.sources?.length ? h("div", {}, fr.sources.map((s) => h("blockquote", {}, s.text, h("small", {}, ` strona ${s.page}`)))) : h("p", { class: "muted" }, "Brak źródła w oryginale (pole dodane przez regułę lub naprawę)."),
    edit);
}

function editForm(f, onApply) {
  const box = ["SECTION", "REPEATING_SECTION"].includes(f.type);
  const title = h("input", { type: "text", value: f.title, "data-testid": "edit-title" });
  const type = h("select", { "data-testid": "edit-type" }, Object.entries(TYPE_PL_EDIT).map(([k, v]) => h("option", { value: k, selected: k === f.type }, v)));
  const req = h("input", { type: "checkbox", checked: f.validation.includes("REQUIRED"), "data-testid": "edit-required" });
  const msg = h("p", { class: "edit-msg", role: "status", "data-testid": "edit-msg" });
  const btns = [];
  const run = async (changes) => {
    btns.forEach((b) => (b.disabled = true)); msg.className = "edit-msg"; msg.textContent = "Sprawdzam reguły…";
    try { await onApply(f.id, changes); }
    catch (e) { msg.className = "edit-msg bad"; msg.textContent = `Nie udało się sprawdzić reguł: ${e.message}`; btns.forEach((b) => (b.disabled = false)); }
  };
  btns.push(
    h("button", { class: "btn small primary", "data-testid": "edit-apply", onclick: () => run({ title: title.value.trim() || f.title, type: box ? f.type : type.value, required: box ? f.validation.includes("REQUIRED") : req.checked }) }, "Zatwierdź i sprawdź reguły"),
    h("button", { class: "btn small", "data-testid": "edit-confirm", onclick: () => run(null) }, "Zatwierdź bez zmian"));
  return h("form", { class: "edit-form", "data-testid": "edit-form", onsubmit: (e) => e.preventDefault() },
    h("h4", {}, "Weryfikacja urzędnika"),
    h("label", {}, "Tytuł", title), box ? null : h("label", {}, "Typ", type),
    box ? null : h("label", { class: "opt" }, req, "Pole wymagane"),
    h("div", { class: "edit-btns" }, btns), msg);
}

/** Podgląd oryginału z nakładką bbox; zwraca {show(sources)}. */
export function renderPreview(root, report) {
  const prev = report.previews || [];
  if (!prev.length) {
    root.replaceChildren(h("p", { class: "muted pad" }, "Brak podglądu. Włącz „Podgląd oryginału” przy konwersji."));
    return { show() {} };
  }
  const wraps = new Map();
  root.replaceChildren(...prev.map((p) => {
    const ov = h("div", { class: "overlay" });
    const w = h("div", { class: "page-prev", "data-page": p.page, style: { aspectRatio: `${p.width} / ${p.height}` } },
      h("img", { alt: `Strona ${p.page} oryginału`, src: `data:image/png;base64,${p.pngBase64}` }), ov);
    wraps.set(p.page, { w, ov, p });
    return h("figure", {}, w, h("figcaption", {}, `Strona ${p.page}`));
  }));
  return {
    show(sources) {
      for (const { ov } of wraps.values()) ov.replaceChildren();
      let first = null;
      for (const s of sources || []) {
        const t = wraps.get(s.page);
        if (!t || !s.bbox) continue;
        const { p } = t, b = s.bbox, pad = 2;
        const el = h("div", { class: "hl", "data-testid": "source-highlight", title: s.text, style: {
          left: `${((b.x - pad) / p.width) * 100}%`, top: `${((b.y - pad) / p.height) * 100}%`,
          width: `${((b.w + 2 * pad) / p.width) * 100}%`, height: `${((b.h + 2 * pad) / p.height) * 100}%` } });
        t.ov.append(el); first ||= el;
      }
      first?.scrollIntoView({ block: "center", behavior: reduce ? "auto" : "smooth" });
    },
  };
}

export { download };
