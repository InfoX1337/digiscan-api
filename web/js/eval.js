const $ = (s) => document.querySelector(s);
const root = document.documentElement;
try { const t = localStorage.getItem("fp-theme"); if (t) root.dataset.theme = t; } catch { /* brak storage */ }
$("#theme").addEventListener("click", () => {
  const dark = root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
  root.dataset.theme = dark ? "light" : "dark";
  try { localStorage.setItem("fp-theme", root.dataset.theme); } catch { /* ignoruj */ }
});

const cls = (v) => (v >= 0.8 ? "hi" : v >= 0.6 ? "mid" : "lo");
const pct = (v) => `${Math.round(v * 100)}%`;
const fmtMs = (ms) => (ms >= 1000 ? `${(ms / 1000).toFixed(1)} s` : `${ms} ms`);

function el(tag, attrs = {}, text) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  if (text !== undefined) e.textContent = text;
  return e;
}

function tile(value, label, extra = "") {
  const t = el("div", { class: `tile ${extra}`.trim() });
  t.append(el("b", {}, value), el("span", {}, label));
  return t;
}

function renderSummary(s) {
  const box = $("#summary");
  const allOk = s.rulesPass === s.rulesTotal;
  box.append(
    tile(`${s.rulesPass}/${s.rulesTotal}`, "reguły COI spełnione (suma po plikach)", allOk ? "ok" : ""),
    tile(`${s.filesAllRulesPass}/${s.files}`, "plików z kompletem reguł", s.filesAllRulesPass === s.files ? "ok" : ""),
    tile(String(s.files), `plików · ${s.forms} formularze · ${s.formats.length} formatów (${s.formats.join(", ")})`),
    tile(pct(s.avgConfidence), "średnia pewność"),
    tile(String(s.repairs), "auto-napraw"),
    tile(fmtMs(s.avgMs), "średni czas na plik"),
  );
  if (s.form1AvgPrecision !== null) {
    box.append(
      tile(pct(s.form1AvgPrecision), "formularz 1: precyzja pól (średnia)"),
      tile(pct(s.form1AvgRecall), "formularz 1: czułość pól (średnia)"),
      tile(pct(s.form1AvgTypeAccuracy), "formularz 1: zgodność typów"),
    );
  }
}

function renderTable(files) {
  const tb = $("#table tbody");
  for (const f of files) {
    const tr = el("tr");
    tr.append(el("td", { class: "name" }, `${f.form}. ${f.formName}`), el("td", { class: "fmt" }, f.format));
    if (!f.ok) {
      tr.className = "err";
      const td = el("td", { colspan: "6" }, "błąd przetwarzania");
      tr.append(td, el("td", { class: "n" }, fmtMs(f.ms)));
    } else {
      const c = el("td", { class: "n" });
      c.append(el("span", { class: `conf ${cls(f.confidence)}` }, f.confidence.toFixed(2)));
      tr.append(
        el("td", { class: "n" }, String(f.fields)),
        el("td", { class: "n" }, String(f.sections)),
        el("td", { class: "n" }, `${f.rulesPass}/${f.rulesTotal}`),
        el("td", { class: "n" }, String(f.repairs)),
        el("td", { class: "n" }, String(f.review)),
        c,
        el("td", { class: "n" }, fmtMs(f.ms)),
      );
    }
    tb.append(tr);
  }
}

function bar(label, v) {
  const b = el("div", { class: "bar" });
  const fill = el("span", { class: `fill ${cls(v)}` });
  fill.style.width = pct(v);
  const track = el("span", { class: "track" });
  track.append(fill);
  b.append(el("span", {}, label), track, el("span", { class: "v" }, pct(v)));
  return b;
}

function renderPr(rows) {
  const box = $("#pr");
  if (!rows.length) { box.append(el("p", { class: "muted" }, "Brak danych porównania.")); return; }
  for (const r of rows) {
    const row = el("div", { class: "prow" });
    const bars = el("div", { class: "bars" });
    bars.append(bar("Precyzja", r.precision), bar("Czułość", r.recall), bar("Zgodność typów", r.typeAccuracy));
    row.append(el("b", { class: "fmt" }, r.format), bars);
    box.append(row);
  }
}

async function main() {
  try {
    const res = await fetch("demo/eval.json", { cache: "no-cache" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const d = await res.json();
    $("#meta").textContent = `Wygenerowano: ${d.generatedAt} · materiały konkursowe, ${d.summary.files} plików`;
    $("#llm-note").textContent = d.llm
      ? "Przebieg z włączonym lokalnym LLM."
      : "Przebieg bez LLM (tylko heurystyki i OCR) – wynik z LLM może być lepszy.";
    renderSummary(d.summary);
    renderTable(d.files);
    renderPr(d.form1);
  } catch (e) {
    const err = $("#error");
    err.hidden = false;
    err.textContent = `Nie udało się wczytać demo/eval.json (${e.message}).`;
    $("#meta").textContent = "";
  }
}
main();
