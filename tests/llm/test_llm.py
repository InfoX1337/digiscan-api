from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path
from typing import Any

import pytest

import formproof.llm as llm
from formproof.config import Settings
from formproof.llm import client
from formproof.llm.fusion import fuse, normalize
from formproof.llm.prompt import build_batches
from formproof.types.draft import DraftField, DraftForm, DraftOption, DraftTab, iter_draft
from formproof.types.source import SourceBlock, SourceDoc

FIX = Path(__file__).parent.parent / "fixtures"


def _doc() -> SourceDoc:
    texts = ["Wniosek o coś", "Czy posiadasz pełnomocnika?", "Tak", "Nie", "Data urodzenia", "Województwo"]
    return SourceDoc(
        filename="x.pdf",
        format="pdf",
        blocks=[SourceBlock(id=f"b{i}", page=1, kind="text", text=t) for i, t in enumerate(texts)],
    )


def _draft() -> DraftForm:
    fields = [
        DraftField(key="f1", type="SECTION", title="Dane", confidence=0.5),
        DraftField(
            key="f2",
            type="RADIO",
            title="Czy posiadasz pełnomocnika?",
            options=[DraftOption(name="Tak"), DraftOption(name="Nie")],
            confidence=0.55,
        ),
        DraftField(key="f3", type="TEXT_FIELD", title="Data urodzenia", confidence=0.5),
        DraftField(key="f4", type="TEXT_FIELD", title="Województwo", confidence=0.5),
        DraftField(key="f5", type="TEXT_FIELD", title="NIP", validation=["NIP"], confidence=0.95),
        DraftField(key="f6", type="TEXT_FIELD", title="Imię pełnomocnika", confidence=0.5),
    ]
    return DraftForm(title="Wniosek", title_confidence=0.4, tabs=[DraftTab(title="Dane", fields=fields)])


def _by_key(d: DraftForm) -> dict[str, DraftField]:
    return {f.key: f for t in d.tabs for f in iter_draft(t.fields)}


@pytest.fixture(autouse=True)
def _settings(monkeypatch: pytest.MonkeyPatch) -> None:
    client.cache_clear()
    s = Settings(llm_enabled=True, ollama_url="http://fake:1", llm_model="fake", llm_timeout_s=5.0)
    monkeypatch.setattr(llm, "get_settings", lambda: s)


def _answer(content: dict[str, Any] | str) -> dict[str, Any]:
    return {"message": {"role": "assistant", "content": content if isinstance(content, str) else json.dumps(content)}}


GOOD = {
    "form_title": "Wniosek o coś",
    "fields": [
        "f1;SECTION;;;Dane wnioskodawcy;",
        "f2;RADIO;;;;",
        "f3;DATEPICKER;;;;",
        "f4;TEXT_FIELD;;Województwo;;",
        "f5;TEXT_FIELD;PESEL;;;",  # pewne pole reguł – nie wolno zmienić
        "f6;TEXT_FIELD;;;;f2=tak",
    ],
}


def test_fusion_agree_disagree_and_additions(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []

    def fake(url: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
        calls.append(payload)
        return _answer(GOOD)

    monkeypatch.setattr(client, "post_json", fake)
    src = _draft()
    res = llm.enrich(_doc(), src)
    assert res.used and res.error is None and res.model == "fake"
    assert len(calls) == 1
    p = calls[0]
    assert p["stream"] is False and p["options"]["temperature"] == 0 and isinstance(p["format"], dict)
    f = _by_key(res.draft)
    assert f["f2"].type == "RADIO" and f["f2"].confidence == pytest.approx(0.59)  # zgoda, nadal do przeglądu
    assert f["f3"].type == "DATEPICKER" and f["f3"].confidence == pytest.approx(0.55)
    assert any(e.by == "llm" and e.reason for e in f["f3"].evidence)
    assert f["f4"].type == "SELECT" and f["f4"].dictionary_name == "Województwo"
    assert f["f1"].title == "Dane wnioskodawcy"
    assert f["f5"].validation == ["NIP"] and f["f5"].confidence == 0.95  # wysoka pewność nietknięta
    assert f["f6"].show_when and f["f6"].show_when[0].when_key == "f2" and f["f6"].show_when[0].equals == "Tak"
    assert res.draft.title == "Wniosek o coś" and res.draft.title_confidence == pytest.approx(0.55)
    assert len(f) == len(_by_key(src))  # nie gubimy pól
    assert _by_key(src)["f3"].type == "TEXT_FIELD"  # wejście niezmienione


def test_fusion_guards() -> None:
    d = _draft()
    fuse(
        d,
        [
            {
                "fields": [
                    "f1;TEXT_FIELD;;;;",  # sekcja nie zmienia się w pole
                    "f2;TEXT_FIELD;;;;",  # pole z opcjami nie traci opcji
                    "f3;SELECT;;;;",  # SELECT bez opcji/słownika – odrzucone
                    "f6;TEXT_FIELD;;;;f2=Może",  # nieistniejąca opcja
                    "f6;NUMBER;;;;",  # duplikat klucza ignorowany
                    "zz;NUMBER;;;;",  # nieznany klucz
                    42,
                    "bez średników",
                ]
            }
        ],
    )
    f = _by_key(d)
    assert f["f1"].type == "SECTION" and f["f2"].type == "RADIO" and f["f3"].type == "TEXT_FIELD"
    assert f["f6"].type == "TEXT_FIELD" and not f["f6"].show_when


def test_normalize_line() -> None:
    n = normalize("f9;text_field;email,nip;;;f2!=Nie")
    assert n is not None
    assert n["type"] == "TEXT_FIELD" and n["validators"] == ["EMAIL", "NIP"]
    assert n["show_when_key"] == "f2" and n["show_when_equals"] == "Nie" and n["show_when_negate"] is True


def test_timeout_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    n = {"calls": 0}

    def fake(url: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
        n["calls"] += 1
        raise TimeoutError("timed out")

    monkeypatch.setattr(client, "post_json", fake)
    src = _draft()
    res = llm.enrich(_doc(), src)
    assert res.used is False and res.draft is src and res.error and "timed out" in res.error
    assert n["calls"] == 2  # 1 retry


def test_invalid_json_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(client, "post_json", lambda url, payload, timeout: _answer("{nie json"))
    src = _draft()
    res = llm.enrich(_doc(), src)
    assert res.used is False and res.draft is src and res.error and "JSON" in res.error


def test_retry_then_success(monkeypatch: pytest.MonkeyPatch) -> None:
    answers = [_answer("[]"), _answer(GOOD)]
    monkeypatch.setattr(client, "post_json", lambda url, payload, timeout: answers.pop(0))
    res = llm.enrich(_doc(), _draft())
    assert res.used and _by_key(res.draft)["f3"].type == "DATEPICKER"


def test_unexpected_exception_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*a: Any, **k: Any) -> Any:
        raise RuntimeError("x")

    monkeypatch.setattr(llm, "build_batches", boom)
    src = _draft()
    res = llm.enrich(_doc(), src)
    assert res.used is False and res.draft is src and res.error


def test_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    n = {"calls": 0}

    def fake(url: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
        n["calls"] += 1
        return _answer(GOOD)

    monkeypatch.setattr(client, "post_json", fake)
    llm.enrich(_doc(), _draft())
    r2 = llm.enrich(_doc(), _draft())
    assert n["calls"] == 1 and r2.used
    monkeypatch.setattr(client, "CACHE_MAX", 1)
    for i in range(3):
        client._cache_put(str(i), {})
    assert len(client._cache) == 1


def test_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(llm, "get_settings", lambda: Settings(llm_enabled=False))
    src = _draft()
    res = llm.enrich(_doc(), src)
    assert res.used is False and res.draft is src


def test_batches_limited_on_fixture() -> None:
    from formproof.infer import infer

    doc = SourceDoc.model_validate_json((FIX / "sample-source.json").read_text())
    bs = build_batches(doc, infer(doc))
    assert 1 <= len(bs) <= 3
    assert all(len(b.user) < 12000 for b in bs)


def _ollama_up(url: str) -> bool:
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/api/version", timeout=1):  # noqa: S310
            return True
    except OSError:
        return False


OLLAMA = os.environ.get("FORMPROOF_TEST_OLLAMA_URL", "http://localhost:11434")


@pytest.mark.skipif(not _ollama_up(OLLAMA), reason="Ollama niedostępna")
def test_integration_ollama(monkeypatch: pytest.MonkeyPatch) -> None:
    from formproof.infer import infer

    s = Settings(llm_enabled=True, ollama_url=OLLAMA, llm_timeout_s=120.0)
    monkeypatch.setattr(llm, "get_settings", lambda: s)
    doc = SourceDoc.model_validate_json((FIX / "sample-source1.json").read_text())
    draft = infer(doc)
    res = llm.enrich(doc, draft)
    assert len(_by_key(res.draft)) == len(_by_key(draft))
    assert res.used or res.error


def test_not_a_field_lowers_confidence_and_keeps_field() -> None:
    from formproof.llm.fusion import fuse_field

    f = DraftField(key="x1", type="TEXT_FIELD", title="Ptoskinia 8", confidence=0.7)
    ch = fuse_field(f, {"key": "x1", "type": "BRAK"}, {"x1": f})
    assert ch == ["nie-pole"] and f.confidence == pytest.approx(0.35) and f.evidence[-1].by == "llm"


def test_section_title_rejects_prompt_echo() -> None:
    from formproof.llm.fusion import fuse_field

    f = DraftField(key="s1", type="SECTION", title="Adres zamieszkania", confidence=0.5)
    fuse_field(f, {"key": "s1", "type": "SECTION", "title": "pokaż_gdy=f5=Polska"}, {"s1": f})
    assert f.title == "Adres zamieszkania"
