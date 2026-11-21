"""E2E UI w trybie demo (/?demo=1). Wymaga: playwright (+ przeglądarka) i działającego serwera.

Uruchomienie: BASE_URL=http://localhost:8000 uv run pytest tests/e2e/ui_test_demo.py
Bez zainstalowanego playwright testy są pomijane.
"""

from __future__ import annotations

import os

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import Page, expect, sync_playwright  # noqa: E402

BASE = os.environ.get("BASE_URL", "http://localhost:8000")
CHROME = os.environ.get("CHROME_PATH") or None


@pytest.fixture(scope="module")
def page():
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=CHROME)
        pg = b.new_page(viewport={"width": 1600, "height": 1000})
        pg.errors = []  # type: ignore[attr-defined]
        pg.on("pageerror", lambda e: pg.errors.append(str(e)))  # type: ignore[attr-defined]
        pg.on("console", lambda m: m.type == "error" and pg.errors.append(m.text))  # type: ignore[attr-defined]
        pg.goto(f"{BASE}/?demo=1")
        yield pg
        b.close()


def test_rules_panel(page: Page) -> None:
    panel = page.get_by_test_id("rules-panel")
    expect(panel).to_be_visible()
    expect(panel).to_contain_text("auto-napraw")
    expect(page.get_by_test_id("rule-COI-TAB-FINISH")).to_be_visible()
    expect(page.get_by_test_id("repairs-list")).to_be_visible()


def test_form_viz_and_review(page: Page) -> None:
    expect(page.get_by_test_id("form-viz")).to_be_visible()
    expect(page.get_by_test_id("field-imie")).to_be_visible()
    page.get_by_role("tab", name="Do przeglądu").click()
    expect(page.get_by_test_id("review-list")).to_be_visible()
    assert page.get_by_test_id("review-item").count() > 0


def test_click_field_highlights_source(page: Page) -> None:
    page.get_by_test_id("field-imie").click()
    expect(page.get_by_test_id("source-highlight").first).to_be_visible()
    expect(page.get_by_role("tab", name="Szczegóły pola")).to_have_attribute("aria-selected", "true")


def test_json_and_download(page: Page) -> None:
    page.get_by_role("tab", name="JSON").click()
    expect(page.get_by_test_id("json-view")).to_contain_text('"tabs"')
    with page.expect_download() as d:
        page.get_by_test_id("download-json").click()
    assert d.value.suggested_filename.endswith(".json")


def test_no_console_errors(page: Page) -> None:
    assert page.errors == []  # type: ignore[attr-defined]


def test_human_confirm_reduces_review(page: Page) -> None:
    page.get_by_role("tab", name="Do przeglądu").click()
    items = page.get_by_test_id("review-item")
    n = items.count()
    items.first.click()
    page.get_by_test_id("edit-confirm").click()
    page.get_by_role("tab", name="Do przeglądu").click()
    expect(page.get_by_test_id("review-item")).to_have_count(n - 1, timeout=10_000)
    assert page.errors == []  # type: ignore[attr-defined]


def test_live_nip_validator(page: Page) -> None:
    import json

    if True:
        pg = page.context.browser.new_context(viewport={"width": 1600, "height": 1000}).new_page()  # type: ignore[union-attr]

        def inject(route):  # wstrzyknięcie walidatora NIP w pierwsze pole tekstowe
            data = json.loads(route.fetch().text())

            def walk(qs):
                for q in qs:
                    f = q["field"]
                    if f["type"] == "TEXT_FIELD" and not f.get("states"):
                        return f
                    r = walk(f.get("repeatingSectionGrid") or [])
                    if r:
                        return r
                return None

            f = next(x for t in data["form"]["tabs"][:1] if (x := walk(t["questions"])))
            f.update(validation=["REQUIRED", "NIP"], readOnly=False, defaultValue="")
            f.pop("defaultValueType", None)
            data["form"]["_nip"] = f["techName"]
            route.fulfill(json=data)

        pg.route("**/demo/sample-response.json", inject)
        pg.goto(f"{BASE}/?demo=1")
        # pierwsze pole z walidatorem NIP: wskazuje je chip „NIP”
        box = pg.locator(".q.t-TEXT_FIELD:has(.chip.val:text-is('NIP')) input").first
        box.fill("5260250275")
        expect(pg.get_by_test_id("field-error").filter(has_text="NIP")).to_be_visible()
        box.fill("5260250274")
        expect(pg.locator(".q-err:visible")).to_have_count(0)
        box.fill("")
        box.blur()
        expect(pg.locator(".q-err:visible")).to_have_text("Pole wymagane")
        pg.context.close()
