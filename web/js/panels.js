import { h, pct, confClass, confLabel, highlightJson, download } from "./util.js";
import { typeLabel } from "./viz.js";

const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;

function countUp(el, to) {
  if (reduce || to === 0) { el.textContent = to; return; }
  const t0 = performance.now();
  const step = (t) => {
    const k = Math.min(1, (t - t0) / 900);
    el.textContent = Math.round(to * (1 - Math.pow(1 - k, 3)));
    if (k < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

const short = (v) => { const s = typeof v === "string" ? v : JSON.stringify(v); return s == null ? "—" : s.length > 80 ? s.slice(0, 77) + "…" : s; };

export function renderRules(root, report) {
  const rules = report.rules || [];
  const ok = rules.filter((r) => r.passed).length;
  const repaired = rules.filter((r) => r.repaired).length;
  const nRep = (report.repairs || []).length;
  const bad = rules.filter((r) => !r.passed);
  const errs = bad.filter((r) => r.severity === "error").length;
  const state = errs ? "fail" : bad.length ? "warn" : "ok";
  const okEl = h("span", { class: "big-n" }, "0");
  const verdict = { ok: "Formularz zgodny z regułami kreatora COI", warn: "Zgodny, z uwagami do sprawdzenia", fail: "Wykryto błędy zgodności" }[state];

  const chips = rules.map((r) => {
    const st = r.passed ? (r.repaired ? "fixed" : "ok") : r.severity === "error" ? "fail" : "warn";
    const lbl = { ok: "OK", fixed: "naprawiono automatycznie", fail: "błąd", warn: "ostrzeżenie" }[st];
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

  root.replaceChildren(...[h("div", { class: `rules-hero ${state}` },
    h("div", { class: "score" },
      h("div", { class: "score-row" }, okEl, h("span", { class: "big-d" }, `/${rules.length}`)),
      h("div", { class: "score-l" }, "reguł COI spełnionych")),
    h("div", { class: "score-side" },
      h("h2", {}, verdict),
      h("p", { class: "pills" },
        h("span", { class: "pill fixed" }, `${nRep} ${plural(nRep, "auto-naprawa", "auto-naprawy", "auto-napraw")}`),
        bad.length ? h("span", { class: `pill ${state}` }, `${bad.length} ${plural(bad.length, "uwaga", "uwagi", "uwag")}`) : null,
        repaired ? h("span", { class: "pill" }, `${repaired} ${plural(repaired, "reguła naprawiona", "reguły naprawione", "reguł naprawionych")}`) : null,
        nFields ? h("span", { class: "pill" }, `${nFields} ${plural(nFields, "element z dowodem", "elementy z dowodem", "elementów z dowodem")}`) : null,
        nReview ? h("span", { class: "pill warn" }, `${nReview} do przeglądu człowieka`) : null),
      h("p", { class: "muted" }, "Walidator sprawdził wynikowy JSON względem reguł kreatora eUsług i poprawił to, co dało się naprawić bez udziału człowieka. Każde pole ma pewność i źródło w oryginale – kliknij pole poniżej."))),
    notOk.length ? h("ul", { class: "rule-grid" }, notOk) : null,
    h("details", { class: "rules-ok", "data-testid": "rules-ok" },
      h("summary", {}, notOk.length ? `Pozostałe reguły spełnione (${okChips.length})` : `Pokaż wszystkie spełnione reguły (${okChips.length})`),
      h("ul", { class: "rule-grid" }, okChips)),
    h("details", { class: "repairs", open: nRep > 0 },
      h("summary", {}, `Wykonane auto-naprawy (${nRep})`),
      nRep ? h("ol", { "data-testid": "repairs-list", class: "repairs-list" }, reps) : h("p", { class: "muted", "data-testid": "repairs-list" }, "Nie była potrzebna żadna naprawa."))].filter(Boolean));
  countUp(okEl, ok);
}

export function plural(n, one, few, many) {
  const m10 = n % 10, m100 = n % 100;
  return n === 1 ? one : m10 >= 2 && m10 <= 4 && !(m100 >= 12 && m100 <= 14) ? few : many;
}

export function renderReview(root, report, onSelect) {
  const items = [...(report.review || [])].sort((a, b) => a.confidence - b.confidence);
  root.replaceChildren(
    h("p", { class: "muted" }, items.length ? `${items.length} ${plural(items.length, "pole wymaga", "pola wymagają", "pól wymaga")} weryfikacji człowieka, od najmniej pewnych.` : "Brak pól wymagających przeglądu."),
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
  root.replaceChildren(h("div", { class: "json-bar" }, h("span", { class: "muted" }, `${(text.length / 1024).toFixed(1)} kB · czysty JSON kreatora eUsług`), copy), pre);
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

export function renderDetails(root, f, fr) {
  if (!f) { root.replaceChildren(h("p", { class: "muted" }, "Kliknij pole w wizualizacji albo pozycję z listy „Do przeglądu”, aby zobaczyć dowód: źródło, pewność i powody decyzji.")); return; }
  const dec = { rules: "reguły", llm: "model językowy", dict: "słownik", repair: "auto-naprawa" };
  root.replaceChildren(
    h("h3", {}, f.title), h("p", { class: "muted" }, `${typeLabel(f.type)} · `, h("code", {}, f.techName)),
    fr ? h("div", { class: `conf-big ${confClass(fr.confidence)}` }, h("b", {}, pct(fr.confidence)), ` pewność ${confLabel(fr.confidence)}`) : h("p", { class: "muted" }, "Brak danych report dla tego pola."),
    fr?.decidedBy?.length ? h("p", {}, "Zdecydowali: ", fr.decidedBy.map((d) => h("span", { class: "chip" }, dec[d] || d))) : null,
    fr?.reasons?.length ? h("div", {}, h("h4", {}, "Powody"), h("ul", {}, fr.reasons.map((r) => h("li", {}, r)))) : null,
    h("h4", {}, "Tekst źródłowy"),
    fr?.sources?.length ? h("div", {}, fr.sources.map((s) => h("blockquote", {}, s.text, h("small", {}, ` strona ${s.page}`)))) : h("p", { class: "muted" }, "Brak źródła w oryginale (pole dodane przez regułę lub naprawę)."));
}

/** Podgląd oryginału z nakładką bbox; zwraca {show(sources)}. */
export function renderPreview(root, report) {
  const prev = report.previews || [];
  if (!prev.length) {
    root.replaceChildren(h("p", { class: "muted pad" }, "Podgląd oryginału niedostępny. Włącz „Podgląd oryginału” przy konwersji; źródło pola zobaczysz w panelu szczegółów."));
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
