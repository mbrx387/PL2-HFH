"""Einrichtungen auswaehlen und E-Mail in der E-Mail-Zentrale vorbereiten.

Der eigentliche mailto:-Aufruf wird bewusst nicht ausgeloest (oeffnet das
lokale Mailprogramm, headless nicht sinnvoll pruefbar).
"""
import re

from helpers import open_directory
from playwright.sync_api import Page, expect


def test_selected_centers_become_email_recipients(page: Page):
    open_directory(page)

    # Ohne E-Mail-Adresse nicht auswaehlbar.
    expect(page.get_by_role("checkbox", name="E2E Seniorenberatung Chemnitz auswählen")).to_be_disabled()

    page.get_by_role("checkbox", name="E2E Pflegestützpunkt Dresden auswählen").check()
    page.get_by_role("checkbox", name="E2E Demenzberatung München auswählen").check()

    bulk = page.locator("#bulk-actions")
    expect(bulk).to_be_visible()
    expect(page.locator("#selected-count")).to_have_text("2")

    bulk.get_by_role("button", name="E-Mail vorbereiten").click()
    expect(page.locator("#view-email")).to_be_visible()
    expect(page.locator("#email-recipient-count")).to_have_text("2")
    expect(page.locator("#email-recipients")).to_have_value(
        "dresden@e2e.example.org, muenchen@e2e.example.org"
    )

    # Betreff ist Pflicht (required): die Browser-Validierung verhindert das
    # Absenden, es wird kein Mailprogramm geoeffnet und nichts vorbereitet.
    subject = page.locator("#email-subject")
    page.locator("#send-email").click()
    assert subject.evaluate("el => el.validity.valueMissing") is True
    expect(subject).to_be_focused()
    expect(page.locator("#email-batches")).to_be_hidden()
    expect(page).to_have_url(re.compile("#email$"))


def test_clearing_selection_hides_bulk_actions(page: Page):
    open_directory(page)

    page.get_by_role("button", name="Alle auf dieser Seite auswählen").click()
    # 5 von 6 Seed-Eintraegen haben eine E-Mail-Adresse.
    expect(page.locator("#selected-count")).to_have_text("5")

    page.get_by_role("button", name="Auswahl aufheben").click()
    expect(page.locator("#bulk-actions")).to_be_hidden()
    expect(page.locator("#dashboard-recipient-count")).to_have_text("0")
