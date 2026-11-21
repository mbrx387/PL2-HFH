"""Gemeinsame Bedienschritte fuer die E2E-Tests."""
from db_seed import SEED_COUNT
from playwright.sync_api import Locator, Page, expect


def open_directory(page: Page) -> None:
    """Oeffnet das Einrichtungsverzeichnis und wartet, bis der Seed geladen ist."""
    page.goto("/#einrichtungen")
    expect(page.locator("#results-count")).to_contain_text(f"{SEED_COUNT} Einrichtungen gefunden")


def card(page: Page, name: str) -> Locator:
    """Karte einer Einrichtung in der Ergebnisliste."""
    return page.locator(".directory-card", has_text=name)


def search(page: Page, term: str) -> None:
    """Sucht ueber das Suchformular nach Name, Ort oder PLZ."""
    page.get_by_label("Suchbegriff").fill(term)
    page.get_by_role("button", name="Einrichtungen suchen").click()
