"""Smoke-Test: Anwendung startet, Startseite und Navigation funktionieren."""
import re

from conftest import SEED_COUNT
from playwright.sync_api import Page, expect


def test_healthz(page: Page):
    res = page.request.get("/healthz")
    assert res.ok
    assert res.json() == {"status": "ok"}


def test_start_page_loads_without_errors(page: Page, console_errors: list[str]):
    page.goto("/")

    expect(page).to_have_title(re.compile("Pflegezentren-Finder"))
    expect(page.locator("#view-einrichtungen")).to_be_visible()
    expect(page.get_by_role("link", name="Einrichtungen")).to_have_attribute("aria-current", "page")
    expect(page.locator("#results-count")).to_contain_text(f"{SEED_COUNT} Einrichtungen gefunden")
    expect(page.locator(".directory-card")).to_have_count(SEED_COUNT)

    page.get_by_role("link", name="Übersicht").click()
    expect(page.locator("#view-dashboard")).to_be_visible()
    expect(page.locator("#view-einrichtungen")).to_be_hidden()
    expect(page.locator("#dashboard-center-count")).to_have_text(str(SEED_COUNT))
    expect(page).to_have_url(re.compile("#dashboard$"))

    # Strenge CSP (app/security.py): Verstoesse und JS-Fehler landen als
    # Konsolenfehler und sollen hier sofort auffallen.
    assert console_errors == []
