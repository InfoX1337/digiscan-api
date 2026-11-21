"""Eval: pipeline na wszystkich materiałach; dla formularza 1 porównanie z expected1.json.

Uruchomienie: uv run python scripts/eval/run.py [--llm] [--only ext,ext]
Wyjście: tabela Markdown na stdout + scripts/eval/out/latest.json. Zawsze exit 0.
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import sys
import time
import unicodedata
from pathlib import Path
from typing import Any

os.environ.setdefault("APP_ENV", "test")

ROOT = Path(__file__).resolve().parents[2]
MATERIALS = ROOT / "tests" / "fixtures" / "materials"
EXPECTED = ROOT / "tests" / "fixtures" / "expected1.json"
OUT = Path(__file__).resolve().parent / "out" / "latest.json"
EXTS = {"pdf", "png", "jpg", "jpeg", "docx", "doc", "xlsx", "ods"}
MATCH_THRESHOLD = 0.78


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.casefold()).replace("ł", "l")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", s)).strip()


def ratio(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()


def collect_fields(form: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    def walk(qs: list[dict[str, Any]]) -> None:
        for q in qs:
            f = q["field"]
            out.append(f)
            walk(f.get("repeatingSectionGrid") or [])

    for t in form.get("tabs", []):
        walk(t.get("questions", []))
    return out


def match_fields(exp: list[dict[str, Any]], got: list[dict[str, Any]]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    en = [norm(f["title"]) for f in exp]
    gn = [norm(f["title"]) for f in got]
    cands = sorted(
        ((ratio(a, b), i, j) for i, a in enumerate(en) for j, b in enumerate(gn)),
        reverse=True,
    )
    ui: set[int] = set()
    uj: set[int] = set()
    pairs = []
    for r, i, j in cands:
        if r < MATCH_THRESHOLD:
            break
        if i in ui or j in uj:
            continue
        ui.add(i)
        uj.add(j)
        pairs.append((exp[i], got[j]))
    return pairs


def compare(expected: dict[str, Any], form: dict[str, Any]) -> dict[str, Any]:
    exp, got = collect_fields(expected), collect_fields(form)
    pairs = match_fields(exp, got)
    m = len(pairs)
    safe = lambda a, b: round(a / b, 3) if b else 0.0  # noqa: E731
    type_ok = sum(e["type"] == g["type"] for e, g in pairs)
    val_ok = sum(sorted(e.get("validation") or []) == sorted(g.get("validation") or []) for e, g in pairs)
    dict_ok = sum(e.get("dictionaryName") == g.get("dictionaryName") for e, g in pairs)
    dv = [(e, g) for e, g in pairs if e.get("defaultValue") not in (None, "", [])]
    dv_ok = sum(e.get("defaultValue") == g.get("defaultValue") for e, g in dv)
    return {
        "expectedFields": len(exp),
        "gotFields": len(got),
        "matched": m,
        "precision": safe(m, len(got)),
        "recall": safe(m, len(exp)),
        "typeAccuracy": safe(type_ok, m),
        "validatorsMatch": safe(val_ok, m),
        "dictionaryMatch": safe(dict_ok, m),
        "defaultValueMatch": safe(dv_ok, len(dv)) if dv else None,
        "sectionsExpected": sum(f["type"] in ("SECTION", "REPEATING_SECTION") for f in exp),
        "sectionsGot": sum(f["type"] in ("SECTION", "REPEATING_SECTION") for f in got),
    }


def list_materials() -> list[Path]:
    if not MATERIALS.exists():
        return []
    res = []
    for p in sorted(MATERIALS.rglob("*")):
        rel = str(p.relative_to(MATERIALS))
        if not p.is_file() or p.suffix.lower().lstrip(".") not in EXTS:
            continue
        if "Materiały do zadania dla Uczestników" in rel or "wizualizacja" in p.name.casefold():
            continue
        res.append(p)
    return res


def form_label(p: Path) -> str:
    m = re.match(r"(\d+)\.", p.relative_to(MATERIALS).parts[0])
    return m.group(1) if m else "?"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm", action="store_true", help="włącz LLM (domyślnie wyłączony)")
    ap.add_argument("--only", default="", help="filtr rozszerzeń, np. pdf,docx")
    args = ap.parse_args()
    if not args.llm:
        os.environ["LLM_ENABLED"] = "false"
    sys.path.insert(0, str(ROOT / "src"))
    from formproof.config import Settings
    from formproof.ingest import ingest
    from formproof.pipeline import ConvertOptions, convert

    cfg = Settings()
    expected = json.loads(EXPECTED.read_text(encoding="utf-8"))
    exp_title = norm(expected["title"])
    only = {e.strip().lower() for e in args.only.split(",") if e.strip()}
    rows: list[dict[str, Any]] = []
    for p in list_materials():
        ext = p.suffix.lower().lstrip(".")
        if only and ext not in only:
            continue
        row: dict[str, Any] = {"form": form_label(p), "file": p.name, "ext": ext}
        row["isForm1"] = ratio(norm(p.stem), exp_title) >= 0.8
        t0 = time.perf_counter()
        try:
            f = ingest(p.name, p.read_bytes(), cfg.max_file_bytes)
            res = convert(f, cfg, ConvertOptions(llm=args.llm, previews=False))
            d = res.dump()
            form, rep = d["form"], d["report"]
            rules = rep.get("rules", [])
            row.update(
                ok=True,
                fields=len(rep.get("fields", {})),
                review=len(rep.get("review", [])),
                rulesPass=sum(r["passed"] for r in rules),
                rulesTotal=len(rules),
                repairs=len(rep.get("repairs", [])),
                confidence=rep.get("confidence"),
            )
            if row["isForm1"]:
                row["compare"] = compare(expected, form)
                row["compare"]["rulePassCount"] = row["rulesPass"]
        except Exception as e:  # noqa: BLE001
            row.update(ok=False, error=f"{type(e).__name__}: {e}")
        row["seconds"] = round(time.perf_counter() - t0, 2)
        rows.append(row)
        print(f"# {row['form']} {p.name}: {'ok' if row['ok'] else row['error']}", file=sys.stderr)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"llm": args.llm, "rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"## Eval (llm={'on' if args.llm else 'off'})\n")
    print("| form | plik | pola | review | reguły | naprawy | conf | czas s |")
    print("|---|---|---|---|---|---|---|---|")
    for r in rows:
        if r["ok"]:
            print(
                f"| {r['form']} | {r['file']} | {r['fields']} | {r['review']} | "
                f"{r['rulesPass']}/{r['rulesTotal']} | {r['repairs']} | {r['confidence']:.2f} | {r['seconds']} |"
            )
        else:
            print(f"| {r['form']} | {r['file']} | BŁĄD: {r['error']} | | | | | {r['seconds']} |")
    f1 = [r for r in rows if r.get("compare")]
    if f1:
        print("\n## Formularz 1 vs expected1.json\n")
        print("| plik | P | R | typ | walid. | słownik | default | sekcje (got/exp) | reguły pass |")
        print("|---|---|---|---|---|---|---|---|---|")
        for r in f1:
            c = r["compare"]
            dv = "-" if c["defaultValueMatch"] is None else c["defaultValueMatch"]
            print(
                f"| {r['file']} | {c['precision']} | {c['recall']} | {c['typeAccuracy']} | {c['validatorsMatch']} | "
                f"{c['dictionaryMatch']} | {dv} | {c['sectionsGot']}/{c['sectionsExpected']} | {c['rulePassCount']} |"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
