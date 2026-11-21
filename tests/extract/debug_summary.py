"""Debug: python tests/extract/debug_summary.py [-v] plik ... – podsumowanie bloków."""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

from formproof.extract import extract
from formproof.types.stages import ExtractInput

FMT = {
    ".pdf": "pdf",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".docx": "docx",
    ".doc": "doc",
    ".xlsx": "xlsx",
    ".ods": "ods",
}


def main(paths: list[str], verbose: bool) -> None:
    for p in paths:
        path = Path(p)
        doc = extract(ExtractInput(path.name, FMT[path.suffix.lower()], path.read_bytes()))  # type: ignore[arg-type]
        kinds = Counter(b.kind for b in doc.blocks)
        print(f"{path.name}: {len(doc.blocks)} blocks {dict(kinds)} ocr={doc.ocr} warnings={doc.warnings}")
        if verbose:
            for b in doc.blocks[:80]:
                print("  ", b.id, b.kind, repr(b.text[:70]), b.table, b.row, b.col, b.checked)


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "-v"]
    main(args, "-v" in sys.argv)
