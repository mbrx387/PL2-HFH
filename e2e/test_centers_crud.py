"""Datenpflege: Einrichtung anlegen, aendern, deaktivieren (Soft-Delete)."""
from conftest import SEED_COUNT
from playwright.sync_api import Page, expect


def open_directory(page: Page) -> None:
    page.goto("/#einrichtungen")
    expect(page.locator("#results-count")).to_contain_text(f"{SEED_COUNT} Einrichtungen gefunden")


def card(page: Page, name: str):
    return page.locator(".directory-card", has_text=name)


def search(page: Page, term: str) -> None:
    page.get_by_label("Suchbegriff").fill(term)
    page.get_by_role("button", name="Einrichtungen suchen").click()


def test_create_center(page: Page):
    open_directory(page)
    page.get_by_role("button", name="+ Einrichtung hinzufügen").click()

    form = page.locator("#center-form")
    expect(page.locator("#center-form-title")).to_have_text("Einrichtung anlegen")
    form.get_by_label("Kennnummer (ID) *").fill("1000001")
    form.get_by_label("Name der Einrichtung *").fill("E2E Neue Beratungsstelle Hamburg")
    form.get_by_label("E-Mail-Adresse").fill("hamburg@e2e.example.org")
    form.get_by_label("Straße und Hausnummer").fill("Neuer Weg 7")
    form.get_by_label("Postleitzahl *").fill("20095")
    form.get_by_label("Stadt / Gemeinde *").fill("Hamburg")
    form.get_by_label("Bundesland *").select_option("HH")
    form.locator("#center-offers").get_by_label("Wohnberatung").check()
    form.get_by_role("button", name="Einrichtung speichern").click()

    expect(page.locator("#center-form-message")).to_have_text("Einrichtung angelegt.")

    # Serverseitig gespeichert ...
    data = page.request.get("/api/centers", params={"search": "Neue Beratungsstelle"}).json()
    assert data["total"] == 1
    created = data["items"][0]
    assert created["id"] == 1000001
    assert created["bundesland"] == "HH"
    assert created["wohnberatung"] is True

    # ... und in der Oberflaeche auffindbar.
    page.get_by_role("link", name="Einrichtungen").click()
    expect(page.locator("#results-count")).to_contain_text(f"{SEED_COUNT + 1} Einrichtungen gefunden")
    search(page, "Hamburg")
    expect(card(page, "E2E Neue Beratungsstelle Hamburg")).to_contain_text("Wohnberatung")


def test_edit_center(page: Page):
    open_directory(page)
    card(page, "E2E Wohnberatung Nürnberg").get_by_role("button", name="Bearbeiten").click()

    expect(page.locator("#center-form-title")).to_have_text("Einrichtung bearbeiten")
    name_field = page.get_by_label("Name der Einrichtung *")
    expect(name_field).to_have_value("E2E Wohnberatung Nürnberg")
    # Datensatz aus dem Import (ID < 1.000.000): Hinweis auf moegliches Ueberschreiben.
    expect(page.locator("#etl-notice")).to_be_visible()

    name_field.fill("E2E Wohnberatung Nürnberg-Mitte")
    page.get_by_role("button", name="Einrichtung speichern").click()
    expect(page.locator("#center-form-message")).to_have_text("Änderungen gespeichert.")

    page.get_by_role("link", name="Einrichtungen").click()
    expect(card(page, "E2E Wohnberatung Nürnberg-Mitte")).to_be_visible()
    expect(page.locator(".directory-card")).to_have_count(SEED_COUNT)


def test_deactivate_center(page: Page):
    open_directory(page)
    card(page, "E2E Betreuungsberatung Augsburg").get_by_role("button", name="Bearbeiten").click()

    page.once("dialog", lambda dialog: dialog.accept())
    page.get_by_role("button", name="Einrichtung deaktivieren").click()

    expect(page.locator("#view-einrichtungen")).to_be_visible()
    expect(page.locator("#results-count")).to_have_text("Einrichtung deaktiviert.")
    expect(page.locator(".directory-card")).to_have_count(SEED_COUNT - 1)
    expect(card(page, "E2E Betreuungsberatung Augsburg")).to_have_count(0)

    page.get_by_role("link", name="Übersicht").click()
    expect(page.locator("#dashboard-center-count")).to_have_text(str(SEED_COUNT - 1))


def test_invalid_postcode_is_rejected_without_request(page: Page):
    open_directory(page)
    write_requests = []
    page.on(
        "request",
        lambda req: write_requests.append(req.url) if req.method != "GET" and "/api/" in req.url else None,
    )

    page.get_by_role("button", name="+ Einrichtung hinzufügen").click()
    page.get_by_label("Kennnummer (ID) *").fill("1000002")
    page.get_by_label("Name der Einrichtung *").fill("E2E Ungültige PLZ")
    page.get_by_label("Postleitzahl *").fill("123")
    page.get_by_label("Stadt / Gemeinde *").fill("Berlin")
    page.get_by_label("Bundesland *").select_option("BE")
    page.get_by_role("button", name="Einrichtung speichern").click()

    expect(page.locator("#center-form-message")).to_have_text(
        "Die Postleitzahl muss aus genau 5 Ziffern bestehen."
    )
    assert write_requests == []
