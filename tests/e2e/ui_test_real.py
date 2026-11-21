"""E2E UI z prawdziwym backendem: upload PDF -> wizualizacja, reguły COI, przegląd, podświetlenie źródła.

Uruchomienie (serwer musi działać): BASE_URL=http://localhost:8000 CHROME_PATH=... \
    uvx --with playwright --with pytest pytest tests/e2e/ui_test_real.py
Scenariusz = baza nagrania wideo demo.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import Page, expect, sync_playwright  # noqa: E402

BASE = os.environ.get("BASE_URL", "http://localhost:8000")
CHROME = os.environ.get("CHROME_PATH") or None
MATERIALS = Path(__file__).resolve().parents[1] / "fixtures" / "materials"
PDF = next(iter(sorted(MATERIALS.rglob("Wniosek o zwrot opłaty skarbowej.pdf"))), None) if MATERIALS.exists() else None

pytestmark = pytest.mark.skipif(PDF is None, reason="materiały poza repo")


@pytest.fixture(scope="module")
def page():
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=CHROME)
        pg = b.new_page(viewport={"width": 1600, "height": 1000})
        pg.errors = []  # type: ignore[attr-defined]
        pg.on("pageerror", lambda e: pg.errors.append(str(e)))  # type: ignore[attr-defined]
        pg.goto(BASE + "/")
        pg.get_by_test_id("upload-input").set_input_files(str(PDF))
        llm = pg.locator("#opt-llm")
        if llm.is_checked():
            llm.uncheck()  # deterministycznie i szybko; LLM sprawdzany osobno
        prev = pg.locator("#opt-previews")
        if not prev.is_checked():
            prev.check()
        pg.get_by_test_id("convert-btn").click()
        expect(pg.get_by_test_id("form-viz")).to_be_visible(timeout=60_000)
        yield pg
        b.close()


def test_rules_panel_real(page: Page) -> None:
    panel = page.get_by_test_id("rules-panel")
    expect(panel).to_be_visible()
    expect(panel).to_contain_text("29")


def test_fields_and_source_highlight(page: Page) -> None:
    fields = page.locator("[data-testid^='field-']")
    assert fields.count() > 10
    fields.first.click()
    expect(page.get_by_test_id("source-highlight").first).to_be_visible()


def test_json_has_title(page: Page) -> None:
    page.get_by_role("tab", name="JSON").click()
    expect(page.get_by_test_id("json-view")).to_contain_text("Wniosek o zwrot opłaty skarbowej")


def test_no_page_errors(page: Page) -> None:
    assert page.errors == []  # type: ignore[attr-defined]
