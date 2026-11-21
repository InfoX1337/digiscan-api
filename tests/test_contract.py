import json

from formproof.types.form import FIELD_TYPES, FormDefinition, iter_questions
from formproof.types.source import SourceDoc

from .conftest import FIXTURES


def test_expected1_parses_and_roundtrips() -> None:
    raw = json.loads((FIXTURES / "expected1.json").read_text())
    f = FormDefinition.model_validate(raw)
    types = {q.field.type for t in f.tabs for q in iter_questions(t.questions)}
    assert types <= set(FIELD_TYPES)
    out = f.dump()
    assert out["tabs"][0]["questions"][0]["field"]["repeatingSectionGrid"]
    assert "repetingSectionGrid" not in json.dumps(out)
    # opcjonalne klucze nie pojawiają się jako null
    assert "null" not in json.dumps(out)


def test_sample_source_has_bboxes() -> None:
    s = SourceDoc.model_validate_json((FIXTURES / "sample-source.json").read_text())
    assert len(s.blocks) > 20
    assert all(b.bbox and b.page >= 1 for b in s.blocks)


def test_sample_response_shape() -> None:
    r = json.loads((FIXTURES / "sample-response.json").read_text())
    FormDefinition.model_validate(r["form"])
    assert r["report"]["fields"]
