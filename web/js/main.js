import { h, $, $$ } from "./util.js";
import { authRequired, demoLogin, setToken, getToken, convertStream, convertBatch, validate } from "./api.js";
import { renderForm, iterQuestions } from "./viz.js";
import { renderRules, renderReview, renderJson, renderReport, renderDetails, renderPreview, download } from "./panels.js";

const params = new URLSearchParams(location.search);
const DEMO = params.get("demo") === "1";
let files = [];
let results = []; // {filename, form, report, error}
let cur = null;

const tokenInput = $("[data-testid=login-token]");
const input = $("[data-testid=upload-input]");
const drop = $("[data-testid=upload-dropzone]");
const btn = $("[data-testid=convert-btn]");
const progress = $("[data-testid=progress]");
const errBox = $("#error");

/* ---------- motyw ---------- */
const root = document.documentElement;
try { const t = localStorage.getItem("fp-theme"); if (t) root.dataset.theme = t; } catch { /* brak storage */ }
$("#theme").addEventListener("click", () => {
  const dark = root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
  root.dataset.theme = dark ? "light" : "dark";
  try { localStorage.setItem("fp-theme", root.dataset.theme); } catch { /* ignoruj */ }
});

/* ---------- auth ---------- */
const authState = $("#auth-state");
async function login() {
  if (await demoLogin()) {
    authState.textContent = authRequired ? "Zalogowano automatycznie (konto demo)" : "";
    tokenInput.hidden = true; return;
  }
  authState.textContent = "Wklej token JWT:"; tokenInput.hidden = false;
}
tokenInput.addEventListener("input", () => setToken(tokenInput.value));

/* ---------- upload ---------- */
function setFiles(list) {
  files = [...list];
  $("#file-list").replaceChildren(...files.map((f) => h("li", {}, f.name, h("small", {}, ` ${(f.size / 1024).toFixed(0)} kB`))));
  btn.disabled = !files.length;
  drop.classList.toggle("has-files", files.length > 0);
}
input.addEventListener("change", () => setFiles(input.files));
["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); }));
["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
drop.addEventListener("drop", (e) => { if (e.dataTransfer?.files?.length) setFiles(e.dataTransfer.files); });
drop.addEventListener("click", () => input.click());
drop.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); input.click(); } });

/* ---------- postęp: prawdziwe etapy z backendu (strumień NDJSON) ---------- */
// etap UI <- etapy pipeline'u (dict + build + validate = walidacja COI)
const STAGES = [
  ["extract", "Odczyt / OCR", ["extract"]],
  ["infer", "Rozpoznanie pól", ["infer"]],
  ["llm", "Model językowy", ["llm"]],
  ["validate", "Walidacja COI", ["dict", "build", "validate"]],
  ["previews", "Podgląd oryginału", ["previews"]],
];
let tick = null;
const fmtS = (ms) => (ms >= 1000 ? `${(ms / 1000).toFixed(1)} s` : `${ms} ms`);

function startProgress({ llm, previews, batch = 0 }) {
  progress.hidden = false;
  clearInterval(tick);
  const items = batch
    ? [["batch", `Przetwarzanie ${batch} plików`, []]]
    : STAGES.filter(([k]) => (k !== "llm" || llm) && (k !== "previews" || previews));
  progress.replaceChildren(h("ol", { class: "stages" }, items.map(([k, l, parts]) =>
    h("li", { "data-stage": k, "data-parts": parts.join(" ") }, h("span", { class: "dot" }), l, h("small", {})))));
  const t0 = {};
  const ms = {};
  if (batch) { const li = $("li", progress); li.className = "active"; t0.batch = performance.now(); }
  tick = setInterval(() => {
    for (const li of $$("li.active", progress)) {
      const k = li.dataset.stage;
      if (t0[k]) $("small", li).textContent = fmtS(Math.round(performance.now() - t0[k]));
    }
  }, 200);
  return {
    stage({ stage, status, ms: took }) {
      const li = $$("li", progress).find((x) => x.dataset.parts.split(" ").includes(stage));
      if (!li) return;
      const k = li.dataset.stage, parts = li.dataset.parts.split(" ");
      if (status === "start" && !t0[k]) { t0[k] = performance.now(); li.className = "active"; }
      if (status === "done") {
        ms[k] = (ms[k] || 0) + (took || 0);
        if (stage === parts[parts.length - 1]) { li.className = "done"; $("small", li).textContent = fmtS(ms[k]); }
      }
    },
    finish(ok) {
      clearInterval(tick);
      for (const li of $$("li", progress)) {
        if (li.className === "done") continue;
        if (!ok && li.className === "active") li.className = "failed";
        else if (ok && li.dataset.stage === "batch") { li.className = "done"; $("small", li).textContent = fmtS(Math.round(performance.now() - t0.batch)); }
        else if (ok) { li.className = "skipped"; $("small", li).textContent = "pominięto"; }
      }
    },
  };
}

function showError(msg, code) {
  errBox.hidden = !msg;
  errBox.replaceChildren(...(msg ? [h("strong", {}, code ? `Błąd ${code}: ` : "Błąd: "), msg] : []));
}

btn.addEventListener("click", async () => {
  if (!files.length) return;
  const llm = $("#opt-llm").checked, previews = $("#opt-previews").checked;
  showError("");
  btn.disabled = true; btn.textContent = "Przetwarzanie…";
  const prog = startProgress({ llm, previews, batch: files.length > 1 ? files.length : 0 });
  try {
    if (files.length === 1) {
      const r = await convertStream(files[0], { llm, previews }, prog.stage);
      results = [{ filename: files[0].name, form: r.form, report: r.report }];
    } else {
      const r = await convertBatch(files, { llm });
      results = r.results.map((x) => ({ filename: x.filename, form: x.form, report: x.report, error: x.ok ? null : x.error }));
    }
    const first = results.find((x) => x.form);
    prog.finish(!!first);
    if (!first) showError(results[0]?.error?.message || "Nie udało się przetworzyć plików.", results[0]?.error?.code);
    show(first || null);
  } catch (e) {
    prog.finish(false);
    showError(e.message, e.code);
  } finally { btn.disabled = false; btn.textContent = "Konwertuj"; }
});

/* ---------- wynik ---------- */
let viz = null, preview = null, activeId = null;
const byId = new Map();

function show(res, keepId = null) {
  cur = res;
  const batchBar = $("#batch-bar");
  batchBar.hidden = results.length < 2;
  batchBar.replaceChildren(...results.map((r) => h("button", { class: `chip-btn${r === res ? " on" : ""}${r.error ? " bad" : ""}`, onclick: () => r.form && show(r) }, r.filename)));
  $("#results").hidden = !res;
  $("#intro").hidden = !!res;
  if (!res) return;
  const { form, report } = res;
  report.fields ||= {}; report.review ||= []; report.rules ||= []; report.repairs ||= [];
  byId.clear();
  for (const t of form.tabs) for (const q of iterQuestions(t.questions)) {
    const f = q.field; // backend pomija puste pola – domyślne wartości dla renderera
    for (const k of ["options", "validation", "states", "repeatingSectionGrid"]) if (!Array.isArray(f[k])) f[k] = []; // {} lub brak = pusta lista
    byId.set(f.id, f);
  }
  $("#form-title").textContent = form.title;
  renderRules($("[data-testid=rules-panel]"), report);
  preview = renderPreview($("#preview"), report);
  viz = renderForm($("[data-testid=form-viz]"), form, report, { onSelect: select });
  renderReview($("#tab-review"), report, select);
  renderJson($("#tab-json"), form);
  renderReport($("#tab-report"), report);
  select(null);
  setTab("review");
  if (keepId && byId.has(keepId)) select(keepId);
  $("#dl").onclick = () => download(`${(report.filename || "formularz").replace(/\.[^.]+$/, "")}.json`, JSON.stringify(form, null, 2));
  if (!keepId) $("#results").scrollIntoView({ behavior: "smooth", block: "start" });
}

function select(id) {
  activeId = id;
  const f = id ? byId.get(id) : null;
  const fr = id ? cur?.report.fields?.[id] : null;
  renderDetails($("#tab-details"), f, fr, applyEdit);
  if (id) { viz.select(id); preview.show(fr?.sources); setTab("details"); }
  else preview?.show([]);
  $$("[data-testid=review-item]").forEach((b) => b.classList.toggle("on", b.dataset.fieldId === id));
}

/** Pętla urzędnika: zmiana pola (changes) lub samo zatwierdzenie (null) -> walidacja COI -> odświeżenie. */
async function applyEdit(id, changes) {
  const f = byId.get(id);
  if (changes) {
    f.title = changes.title; f.type = changes.type;
    f.validation = changes.required ? [...new Set([...f.validation, "REQUIRED"])] : f.validation.filter((v) => v !== "REQUIRED");
  }
  const r = await validate(cur.form);
  const rep = cur.report;
  cur.form = r.form; rep.rules = r.rules; rep.repairs = r.repairs;
  const fr = (rep.fields[id] ||= { confidence: 1, decidedBy: [], reasons: [], sources: [] });
  fr.confidence = 1;
  if (!(fr.decidedBy ||= []).includes("human")) fr.decidedBy.push("human");
  if (!(fr.reasons ||= []).includes("zatwierdzone przez urzędnika")) fr.reasons.push("zatwierdzone przez urzędnika");
  rep.review = rep.review.filter((x) => x.fieldId !== id);
  show(cur, id);
}

function setTab(name) {
  $$(".rtab").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === name)));
  $$(".tabpanel").forEach((p) => (p.hidden = p.id !== `tab-${name}`));
}
$$(".rtab").forEach((b) => b.addEventListener("click", () => setTab(b.dataset.tab)));

/* ---------- start ---------- */
(async () => {
  if (DEMO) {
    try {
      const r = await (await fetch("demo/sample-response.json")).json();
      results = [{ filename: r.report.filename, form: r.form, report: r.report }];
      authState.textContent = "Tryb demo: dane przykładowe (bez backendu)";
      tokenInput.hidden = true;
      $("#demo-badge").hidden = false;
      show(results[0]);
      scrollTo(0, 0);
    } catch (e) { showError("Nie udało się wczytać danych demo: " + e.message); }
    login().catch(() => {});
  } else await login();
})();
export { getToken };
