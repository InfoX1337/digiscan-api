"""E2E UI: plik z kilkoma wnioskami (spis 'Rodzaje wniosków') -> wybór rodzaju wniosku steruje sekcjami.

Uruchomienie (serwer musi działać): BASE_URL=http://localhost:8000 CHROME_PATH=... \
    uvx --with playwright --with pytest pytest -o addopts="" tests/e2e/ui_test_variants.py
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
PDF = next(iter(sorted(MATERIALS.rglob("Wniosek o przyznanie stypendium.pdf"))), None) if MATERIALS.exists() else None

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
            llm.uncheck()
        pg.get_by_test_id("convert-btn").click()
        expect(pg.get_by_test_id("form-viz")).to_be_visible(timeout=60_000)
        yield pg
        b.close()


def _sec(page: Page, needle: str):  # type: ignore[no-untyped-def]
    return page.locator("section.q", has=page.locator("h3", has_text=needle)).first


def test_variant_choice_drives_sections(page: Page) -> None:
    choice = page.get_by_test_id("field-wybierz_rodzaj_wniosku")
    expect(choice).to_be_visible()
    expect(choice.locator("label.opt")).to_have_count(3)
    stypendium = _sec(page, "kandydata do stypendium")
    nagroda = _sec(page, "kandydata do nagrody")
    expect(stypendium).to_be_hidden()
    expect(nagroda).to_be_hidden()
    choice.locator("label.opt", has_text="nagrody").click()
    expect(nagroda).to_be_visible()
    expect(stypendium).to_be_hidden()
    choice.locator("label.opt", has_text="stypendium").click()
    expect(stypendium).to_be_visible()
    expect(nagroda).to_be_hidden()


def test_title_combined(page: Page) -> None:
    page.get_by_role("tab", name="JSON").click()
    title = "Wniosek o przyznanie stypendium, nagrody lub wyróżnienia sportowego"
    expect(page.get_by_test_id("json-view")).to_contain_text(title)


def test_no_page_errors(page: Page) -> None:
    assert page.errors == []  # type: ignore[attr-defined]
