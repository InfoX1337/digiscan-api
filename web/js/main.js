import { h, $, $$ } from "./util.js";
import { demoLogin, setToken, getToken, convert, convertBatch } from "./api.js";
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
  if (await demoLogin()) { authState.textContent = "Zalogowano automatycznie (konto demo)"; tokenInput.hidden = true; return; }
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

/* ---------- postęp (etapy szacowane po stronie klienta, backend nie streamuje) ---------- */
const STAGES = [["extract", "Odczyt / OCR"], ["infer", "Rozpoznanie pól"], ["llm", "Model językowy"], ["validate", "Walidacja COI"]];
let timer = null;
function startProgress(useLlm) {
  const stages = STAGES.filter(([k]) => useLlm || k !== "llm");
  progress.hidden = false;
  progress.replaceChildren(h("ol", { class: "stages" }, stages.map(([k, l]) => h("li", { "data-stage": k }, h("span", { class: "dot" }), l, h("small", {})))));
  let i = 0;
  const mark = () => $$("li", progress).forEach((li, j) => { li.className = j < i ? "done" : j === i ? "active" : ""; });
  mark();
  clearInterval(timer);
  timer = setInterval(() => { if (i < stages.length - 1) { i++; mark(); } }, 1800);
}
function finishProgress(timings, ok = true) {
  clearInterval(timer);
  $$("li", progress).forEach((li) => {
    const t = timings?.[li.dataset.stage];
    li.className = ok ? "done" : "failed";
    $("small", li).textContent = t != null ? `${t} ms` : "";
  });
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
  startProgress(llm);
  try {
    if (files.length === 1) {
      const r = await convert(files[0], { llm, previews });
      results = [{ filename: files[0].name, form: r.form, report: r.report }];
    } else {
      const r = await convertBatch(files, { llm });
      results = r.results.map((x) => ({ filename: x.filename, form: x.form, report: x.report, error: x.ok ? null : x.error }));
    }
    const first = results.find((x) => x.form);
    finishProgress(first?.report?.timings, !!first);
    if (!first) showError(results[0]?.error?.message || "Nie udało się przetworzyć plików.", results[0]?.error?.code);
    show(first || null);
  } catch (e) {
    finishProgress(null, false);
    showError(e.message, e.code);
  } finally { btn.disabled = false; btn.textContent = "Konwertuj"; }
});

/* ---------- wynik ---------- */
let viz = null, preview = null, activeId = null;
const byId = new Map();

function show(res) {
  cur = res;
  const batchBar = $("#batch-bar");
  batchBar.hidden = results.length < 2;
  batchBar.replaceChildren(...results.map((r) => h("button", { class: `chip-btn${r === res ? " on" : ""}${r.error ? " bad" : ""}`, onclick: () => r.form && show(r) }, r.filename)));
  $("#results").hidden = !res;
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
  $("#dl").onclick = () => download(`${(report.filename || "formularz").replace(/\.[^.]+$/, "")}.json`, JSON.stringify(form, null, 2));
  $("#results").scrollIntoView({ behavior: "smooth", block: "start" });
}

function select(id) {
  activeId = id;
  const f = id ? byId.get(id) : null;
  const fr = id ? cur?.report.fields?.[id] : null;
  renderDetails($("#tab-details"), f, fr);
  if (id) { viz.select(id); preview.show(fr?.sources); setTab("details"); }
  else preview?.show([]);
  $$("[data-testid=review-item]").forEach((b) => b.classList.toggle("on", b.dataset.fieldId === id));
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
