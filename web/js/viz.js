import { validateValue } from "./validators.js";
import { h, $$, pct, confClass, safeHtml, hasText } from "./util.js";

const CONTAINERS = new Set(["SECTION", "REPEATING_SECTION"]);
const TYPE_PL = { TEXT_FIELD: "Tekst", TEXTAREA: "Tekst wieloliniowy", NUMBER: "Liczba", DATEPICKER: "Data", SELECT: "Lista", RADIO: "Wybór", CHECKBOX: "Checkbox", FILE_UPLOADER: "Załącznik", CONSENT_SECTION: "Zgody", TEXT_BLOCK: "Blok tekstu", INFO_SECTION: "Informacja", SECTION: "Sekcja", REPEATING_SECTION: "Sekcja powtarzalna" };
export const TYPE_PL_EDIT = Object.fromEntries(Object.entries(TYPE_PL).filter(([k]) => !CONTAINERS.has(k)));
export const typeLabel = (t) => TYPE_PL[t] || t;

export function* iterQuestions(qs) {
  for (const q of qs || []) { yield q; yield* iterQuestions(q.field.repeatingSectionGrid); }
}

export function renderForm(root, form, report, { onSelect }) {
  const answers = {};
  const known = new Set();
  for (const t of form.tabs) for (const q of iterQuestions(t.questions)) known.add(q.field.techName);
  const conditional = [];
  let showAll = false;

  const stepper = h("div", { class: "stepper", role: "tablist" });
  const pages = h("div", { class: "pages" });
  const note = h("div", { class: "cond-note" });
  root.replaceChildren(stepper, pages, note);

  function badge(f) {
    const r = report.fields?.[f.id];
    if (!r) return null;
    return h("span", { class: `conf ${confClass(r.confidence)}`, title: `Pewność ${pct(r.confidence)}` }, pct(r.confidence));
  }
  function control(f) {
    const ext = f.defaultValueType === "EXTERNAL_SYSTEM";
    const dv = ext ? undefined : Array.isArray(f.defaultValue) ? f.defaultValue[0] : f.defaultValue;
    const ro = f.readOnly;
    if (ext && !["SELECT", "RADIO", "CHECKBOX"].includes(f.type)) return h("input", { type: "text", readonly: true, placeholder: "uzupełni system po zalogowaniu (rejestr)" });
    const rec = (v) => { answers[f.techName] = v; applyStates(); };
    const vals = f.validation;
    const check = (e, final) => {
      const box = e.target.closest(".q"), err = box.querySelector(".q-err");
      const empty = !String(e.target.value).trim();
      const msg = empty && !final ? null : validateValue(e.target.value, vals);
      err.textContent = msg || ""; err.hidden = !msg;
      e.target.classList.toggle("invalid", !!msg);
      if (msg) e.target.setAttribute("aria-invalid", "true"); else e.target.removeAttribute("aria-invalid");
    };
    const live = { oninput: (e) => { rec(e.target.value); check(e, false); }, onblur: (e) => check(e, true) };
    switch (f.type) {
      case "TEXTAREA": return h("textarea", { rows: 3, readonly: ro, ...live }, dv || "");
      case "NUMBER": return h("input", { type: "number", value: dv, readonly: ro, ...live });
      case "DATEPICKER": return h("input", { type: "date", value: dv, readonly: ro, onchange: (e) => rec(e.target.value) });
      case "SELECT": {
        const s = h("select", { disabled: ro, onchange: (e) => rec(e.target.value) }, h("option", { value: "" }, f.dictionaryName ? `Słownik: ${f.dictionaryName}` : "Wybierz…"));
        for (const o of f.options) s.append(h("option", { value: o.name }, o.name));
        if (dv && ![...s.options].some((o) => o.value === dv)) s.append(h("option", { value: dv }, dv));
        if (dv) { s.value = dv; answers[f.techName] = dv; }
        return s;
      }
      case "RADIO": return h("div", { class: "opts" }, f.options.map((o) => h("label", { class: "opt" }, h("input", { type: "radio", name: f.id, onchange: () => rec(o.name) }), o.name)));
      case "CHECKBOX": {
        const set = new Set(); answers[f.techName] = set;
        const opts = f.options.length ? f.options : [{ name: f.title }];
        return h("div", { class: "opts" }, opts.map((o) => h("label", { class: "opt" }, h("input", { type: "checkbox", onchange: (e) => { e.target.checked ? set.add(o.name) : set.delete(o.name); applyStates(); } }), o.name)));
      }
      case "FILE_UPLOADER": return h("div", { class: "file-ph" }, "Przeciągnij plik lub wybierz z dysku");
      case "CONSENT_SECTION": return h("div", { class: "opts" }, (f.consentSectionConfig?.consents || []).map((c) => h("label", { class: "opt" }, h("input", { type: "checkbox" }), c.description)));
      default: return h("input", { type: "text", value: dv, readonly: ro, ...live });
    }
  }
  function renderQ(q) {
    const f = q.field;
    const style = { gridArea: `${q.y + 1} / ${q.x + 1} / span ${q.rows || 1} / span ${q.cols || 1}` };
    const attrs = { class: `q t-${f.type}`, style, "data-testid": `field-${f.techName}`, "data-field-id": f.id, "data-type": f.type, tabindex: 0 };
    let el;
    if (CONTAINERS.has(f.type)) {
      el = h("section", attrs,
        h("header", { class: "q-head" }, h("h3", {}, f.title), badge(f)),
        hasText(f.description) ? h("div", { class: "desc" }, safeHtml(f.description)) : null,
        h("div", { class: "grid nested" }, (f.repeatingSectionGrid || []).map(renderQ)));
    } else if (f.type === "TEXT_BLOCK" || f.type === "INFO_SECTION") {
      el = h("div", { ...attrs, class: `${attrs.class} block` }, f.title ? h("strong", {}, f.title) : null, h("div", { class: "desc" }, safeHtml(f.description)), badge(f));
    } else {
      const req = f.validation.includes("REQUIRED");
      el = h("div", attrs,
        h("label", { class: "q-label" }, f.title, req ? h("span", { class: "req", title: "Pole wymagane", "aria-label": "wymagane" }, "*") : null,
          f.tooltipMessage ? h("span", { class: "tip", title: f.tooltipMessage }, "i") : null, badge(f)),
        control(f),
        h("div", { class: "q-err", role: "alert", "data-testid": "field-error", hidden: true }),
        h("div", { class: "q-meta" },
          f.readOnly ? h("span", { class: "chip ro" }, "tylko do odczytu") : null,
          f.defaultValueType === "EXTERNAL_SYSTEM" ? h("span", { class: "chip ext" }, `dane z systemu: ${f.defaultValue}`) : null,
          f.validation.filter((v) => v !== "REQUIRED").map((v) => h("span", { class: "chip val" }, v)),
          f.states.length ? h("span", { class: "chip cond", title: "Pole warunkowe" }, "warunek") : null));
    }
    if (f.states.length) conditional.push({ el, f });
    return el;
  }
  function showTab(i) {
    $$(".step", stepper).forEach((s, j) => s.setAttribute("aria-selected", String(j === i)));
    $$(".page", pages).forEach((p, j) => (p.hidden = j !== i));
  }
  form.tabs.forEach((t, i) => {
    stepper.append(h("button", { class: "step", role: "tab", onclick: () => showTab(i) }, h("span", { class: "n" }, i + 1), t.title, t.type === "FINISH" ? h("em", {}, "koniec") : null));
    pages.append(h("div", { class: "page", role: "tabpanel" }, h("div", { class: "grid" }, t.questions.map(renderQ))));
  });

  /** Best effort dla JSONata: ("wartość" in ...['techName' in field.techName].field.__userAnswer) */
  function evalState(s) {
    const q = s.query || "";
    const clauses = [...q.matchAll(/"((?:[^"\\]|\\.)*)"\s+in\s+([^"]*?)\.field\.__userAnswer/g)];
    if (!clauses.length) return true;
    const res = [];
    for (const c of clauses) {
      const names = [...c[2].matchAll(/\['([^']+)'\s+in\s+field\.techName\]/g)];
      const tn = names.at(-1)?.[1];
      if (!tn || !known.has(tn)) return true;
      const a = answers[tn];
      res.push(a instanceof Set ? a.has(c[1]) : a === c[1]);
    }
    let v = / or /.test(q) ? res.some(Boolean) : res.every(Boolean);
    if (/\$not\s*\(/.test(q)) v = !v;
    return v;
  }
  function applyStates() {
    let hidden = 0;
    for (const { el, f } of conditional) {
      let vis = true;
      for (const s of f.states) { const r = evalState(s); vis = s.type === "HIDE" ? vis && !r : vis && r; }
      el.hidden = !showAll && !vis;
      el.classList.toggle("cond-off", showAll && !vis);
      if (el.hidden) hidden++;
    }
    note.replaceChildren();
    if (conditional.length) {
      note.append(h("span", {}, `Pola warunkowe: ${conditional.length}${hidden ? `, ukryte ${hidden}` : ""}. `),
        h("label", { class: "opt" }, h("input", { type: "checkbox", checked: showAll, onchange: (e) => { showAll = e.target.checked; applyStates(); } }), "pokaż wszystkie niezależnie od warunków"));
    }
  }
  root.addEventListener("click", (e) => {
    const q = e.target.closest?.("[data-field-id]");
    if (q) onSelect(q.dataset.fieldId);
  });
  root.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && e.target.matches?.("[data-field-id]")) onSelect(e.target.dataset.fieldId);
  });
  showTab(0); applyStates();

  return {
    select(id) {
      $$(".q.selected", root).forEach((x) => x.classList.remove("selected"));
      const el = root.querySelector(`[data-field-id="${id}"]`);
      if (!el) return;
      showTab($$(".page", pages).indexOf(el.closest(".page")));
      if (el.hidden) { showAll = true; applyStates(); }
      el.classList.add("selected");
      el.scrollIntoView({ block: "nearest", behavior: "smooth" });
    },
  };
}
