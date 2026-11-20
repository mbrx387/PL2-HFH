"""Einrichtungen anzeigen, suchen und filtern."""
from db_seed import SEED_COUNT
from helpers import card, open_directory, search
from playwright.sync_api import Page, expect


def test_search_by_city(page: Page):
    open_directory(page)

    search(page, "Leipzig")

    cards = page.locator(".directory-card")
    expect(cards).to_have_count(1)
    expect(cards.first).to_contain_text("E2E Angehörigenberatung Leipzig")
    expect(cards.first).to_contain_text("04109 Leipzig")
    expect(page.locator("#results-count")).to_contain_text("1 Einrichtungen gefunden")


def test_filter_by_state_and_offer_then_reset(page: Page):
    open_directory(page)

    page.get_by_label("Bundesland", exact=True).select_option("BY")
    expect(page.locator("#results-count")).to_contain_text("3 Einrichtungen gefunden")
    expect(card(page, "Sachsen")).to_have_count(0)

    page.get_by_label("Angebot", exact=True).select_option("demenzberatung")
    cards = page.locator(".directory-card")
    expect(cards).to_have_count(1)
    expect(cards.first).to_contain_text("E2E Demenzberatung München")

    page.get_by_role("button", name="Filter zurücksetzen").click()
    expect(page.locator("#results-count")).to_contain_text(f"{SEED_COUNT} Einrichtungen gefunden")
    expect(cards).to_have_count(SEED_COUNT)


def test_search_without_hits_shows_empty_state(page: Page):
    open_directory(page)

    search(page, "Gibt-es-nicht")

    expect(page.locator("#results-count")).to_have_text("Keine Einrichtungen gefunden.")
    expect(page.locator(".directory-card")).to_have_count(0)
