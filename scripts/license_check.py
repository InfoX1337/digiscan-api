"""Blokuje zależności copyleft (GPL/AGPL/LGPL/SSPL/EUPL) i bez licencji.

Uruchom: uv run python scripts/license_check.py
"""

import json
import re
import subprocess
import sys

BAD = re.compile(r"\b(A?GPL|LGPL|SSPL|EUPL|General Public License|CC-BY-NC)", re.I)
out = subprocess.run(
    [sys.executable, "-m", "piplicenses", "--from=mixed", "--format=json"], capture_output=True, text=True, check=True
).stdout
bad = []
for p in json.loads(out):
    lic = p["License"]
    alts = re.split(r"\s+OR\s+|;\s*", lic.replace("(", "").replace(")", ""))
    if lic.upper() == "UNKNOWN" or all(BAD.search(a) for a in alts):
        bad.append(f"{p['Name']}=={p['Version']} ({lic})")
print(f"Sprawdzono {len(json.loads(out))} pakietów.")
if bad:
    print("ZABRONIONE/NIEZNANE licencje:\n  " + "\n  ".join(bad))
    sys.exit(1)
print("OK – brak copyleft.")
