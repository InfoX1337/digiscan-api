import json
from pathlib import Path

EVAL = Path(__file__).resolve().parents[2] / "web" / "demo" / "eval.json"


def test_eval_json_shape() -> None:
    d = json.loads(EVAL.read_text(encoding="utf-8"))
    assert {"generatedAt", "llm", "summary", "files", "form1"} <= d.keys()
    assert d["files"]
    for f in d["files"]:
        assert {"form", "formName", "format", "ok", "ms"} <= f.keys()
        if f["ok"]:
            assert {"fields", "sections", "rulesPass", "rulesTotal", "repairs", "review", "confidence"} <= f.keys()
            assert f["rulesPass"] <= f["rulesTotal"]
    s = d["summary"]
    assert {"files", "rulesPass", "rulesTotal", "avgConfidence", "avgMs", "formats"} <= s.keys()
    assert s["files"] == len(d["files"])
    for r in d["form1"]:
        assert {"format", "precision", "recall", "typeAccuracy"} <= r.keys()
