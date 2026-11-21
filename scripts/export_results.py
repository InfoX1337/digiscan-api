"""Eksport wynikowych JSON-ów (form + report) dla wszystkich plików formularzy z katalogu materiałów.

uv run python scripts/export_results.py [katalog_materiałów] [katalog_wyjścia] [--llm]
Wynik: <wyjście>/<nazwa pliku>.json (czysty form wg schemy COI) i <nazwa pliku>.report.json.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from formproof.config import Settings
from formproof.ingest import IngestError, ingest
from formproof.pipeline import ConvertOptions, convert

EXTS = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".docx", ".doc", ".xlsx", ".ods"}


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    src = Path(args[0] if args else "tests/fixtures/materials")
    out = Path(args[1] if len(args) > 1 else "wyniki")
    llm = "--llm" in sys.argv
    cfg = Settings()
    out.mkdir(parents=True, exist_ok=True)
    n = 0
    for p in sorted(src.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in EXTS or "wizualizacja" in p.name.casefold():
            continue
        if p.parent == src or "Materiały do zadania" in str(p):
            continue  # dokumenty pomocnicze zadania, nie formularze
        try:
            r = convert(ingest(p.name, p.read_bytes(), cfg.max_file_bytes), cfg, ConvertOptions(llm=llm))
        except IngestError as e:
            print(f"pominięto {p.name}: {e}")
            continue
        d = r.dump()
        stem = f"{p.stem}.{p.suffix.lstrip('.').lower()}"
        (out / f"{stem}.json").write_text(json.dumps(d["form"], ensure_ascii=False, indent=2), encoding="utf-8")
        rep = json.dumps(d["report"], ensure_ascii=False, indent=2)
        (out / f"{stem}.report.json").write_text(rep, encoding="utf-8")
        n += 1
        print(f"{stem}: pola={len(r.report.fields)} przegląd={len(r.report.review)} pewność={r.report.confidence}")
    print(f"zapisano {n} formularzy do {out}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
