import pytest
from fastapi.testclient import TestClient

OIDC_ENV = {
    "AUTH_ENABLED": "true",
    "OIDC_ISSUER": "http://kc.test/idp/realms/hfh-pflege",
    "OIDC_CLIENT_ID": "pflege-finder",
    "OIDC_CLIENT_SECRET": "s3cret-but-not-a-placeholder",
}


def test_healthz(client):
    assert client.get("/healthz").json() == {"status": "ok"}


def test_index_renders(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "Content-Security-Policy" in res.headers
    assert "unsafe-inline" not in res.headers["Content-Security-Policy"]
    # Neue Oberflaeche (aus frontend/ integriert) mit eigenem Skript.
    # Mit Versions-Parameter, damit nginx die Datei lange cachen darf.
    assert 'src="/static/js/main.js?v=' in res.text
    assert 'href="/static/css/style.css?v=' in res.text
    assert 'id="view-einrichtungen"' in res.text


@pytest.mark.parametrize(("tag", "expected"), [("sha-1a2b3c4", "sha-1a2b3c4"), ("latest", None), ("", None)])
def test_asset_version_follows_image_tag(monkeypatch, tag, expected):
    from app.main import _asset_version

    monkeypatch.setenv("IMAGE_TAG", tag)
    version = _asset_version()
    if expected:
        assert version == expected
    else:
        # Kein echter Tag: Startzeitpunkt, damit Browser lokal nicht ewig cachen.
        assert version.isdigit()


def test_static_assets_are_served(client):
    assert client.get("/static/js/main.js").status_code == 200
    assert client.get("/static/css/style.css").status_code == 200


@pytest.mark.parametrize(("role", "shows_editor"), [("reader", False), ("editor", True), ("admin", True)])
def test_index_shows_data_maintenance_only_for_editors(make_app, monkeypatch, role, shows_editor):
    app = make_app(**OIDC_ENV)
    from app.auth import oauth

    async def authorize_access_token(request):
        return {
            "userinfo": {
                "sub": "u",
                "email": "u@example.org",
                "name": "Test Person",
                "roles": [role],
                "sid": "test-session-id",
            },
            "id_token": "t",
        }

    monkeypatch.setattr(oauth.keycloak, "authorize_access_token", authorize_access_token)

    async def mock_validate_keycloak_session(user):
        return bool(user.get("sub") and user.get("sid"))

    monkeypatch.setattr(
        "app.auth.validate_keycloak_session",
        mock_validate_keycloak_session,
    )

    with TestClient(app) as role_client:
        assert role_client.get("/auth/callback", follow_redirects=False).status_code == 307
        response = role_client.get("/", follow_redirects=False)
        assert response.status_code == 200
        page = response.text

    assert ('id="view-datenpflege"' in page) is shows_editor
    assert (f'data-can-edit="{"true" if shows_editor else "false"}"') in page
    assert "Test Person" in page


def test_list_centers_uses_csv_ids(client):
    data = client.get("/api/centers").json()
    assert data["total"] == 3
    assert sorted(c["id"] for c in data["items"]) == [10, 20, 30]


def test_filter_bundesland_case_insensitive(client):
    data = client.get("/api/centers", params={"bundesland": "sn"}).json()
    assert data["total"] == 2
    assert {c["ort"] for c in data["items"]} == {"Dresden", "Leipzig"}


def test_filter_angebot(client):
    data = client.get("/api/centers", params={"angebot": "demenzberatung"}).json()
    assert [c["id"] for c in data["items"]] == [30]


def test_invalid_angebot_rejected(client):
    assert client.get("/api/centers", params={"angebot": "foo"}).status_code == 422


def test_search_escapes_like_wildcards(client):
    # Ohne Escaping wuerde "%" bzw. "_" als Wildcard alle Eintraege treffen.
    assert client.get("/api/centers", params={"search": "%"}).json()["total"] == 0
    assert client.get("/api/centers", params={"search": "_"}).json()["total"] == 0
    assert client.get("/api/centers", params={"search": "Leip"}).json()["total"] == 1


def test_pagination_total_independent_of_limit(client):
    data = client.get("/api/centers", params={"limit": 1}).json()
    assert data["total"] == 3
    assert len(data["items"]) == 1


def test_limit_capped(client):
    assert client.get("/api/centers", params={"limit": 501}).status_code == 422


def test_bundeslaender(client):
    assert client.get("/api/bundeslaender").json() == ["BY", "SN"]


def _center_payload(center_id=None):
    payload = {
        "name": "Neue Beratungsstelle",
        "bundesland": "sn",
        "plz": "01069",
        "ort": "Dresden",
        "adresse": "Neue Straße 1",
        "email": "neu@example.org",
        "telefon": "0351 123456",
        "website": "https://example.org",
        "latitude": 51.0,
        "longitude": 13.7,
        "services": ["Pflegeberatung"],
    }
    if center_id is not None:
        payload["id"] = center_id
    return payload


def test_create_center(client):
    # Issue #85: Die ID vergibt der Server (ab 1.000.000), nicht der Client.
    response = client.post("/api/centers", json=_center_payload(40))

    assert response.status_code == 201
    assert response.json()["id"] >= 1_000_000  # im manuellen ID-Bereich
    assert response.json()["bundesland"] == "SN"
    assert response.json()["leistungen"] == "Pflegeberatung"
    assert response.json()["manuell_gepflegt"] is True  # Neuanlage ist import-gesperrt
    assert response.json()["aktiv"] is True


def test_create_center_assigns_distinct_auto_ids(client):
    first = client.post("/api/centers", json=_center_payload()).json()
    second = client.post("/api/centers", json=_center_payload()).json()

    assert first["id"] != second["id"]
    assert first["id"] >= 1_000_000 and second["id"] > first["id"]


def test_create_center_rejects_unknown_service(client):
    payload = _center_payload(40)
    payload["services"] = ["Unknown"]

    assert client.post("/api/centers", json=payload).status_code == 422


def test_create_center_rejects_invalid_website_server_side(client):
    # Issue #85: Website-Pruefung serverseitig, nicht nur im Browser.
    payload = _center_payload()
    payload["website"] = "example.org"

    assert client.post("/api/centers", json=payload).status_code == 422


def test_update_center_replaces_data_and_services_and_sets_lock(client):
    response = client.put("/api/centers/10", json=_center_payload())

    assert response.status_code == 200
    assert response.json()["name"] == "Neue Beratungsstelle"
    assert response.json()["leistungen"] == "Pflegeberatung"
    # Issue #85: manuelle Aenderung sperrt den Eintrag fuer den Import.
    assert response.json()["manuell_gepflegt"] is True
    assert response.json()["manuell_geaendert_am"] is not None


def test_update_center_returns_not_found(client):
    assert client.put("/api/centers/999", json=_center_payload()).status_code == 404


def test_delete_center(client):
    response = client.delete("/api/centers/30")

    assert response.status_code == 204
    assert client.get("/api/centers").json()["total"] == 2
    assert client.get("/api/bundeslaender").json() == ["SN"]
    assert client.put("/api/centers/30", json=_center_payload()).status_code == 200
    assert client.get("/api/centers").json()["total"] == 3


def test_delete_center_sets_manual_lock_and_hides_from_default_list(client):
    assert client.delete("/api/centers/30").status_code == 204

    # Deaktivierte erscheinen nicht in der normalen Liste ...
    assert [c["id"] for c in client.get("/api/centers").json()["items"]] == [10, 20]
    # ... aber mit ?aktiv=false (ohne Login im Dev-Modus erlaubt) inklusive Sperrvermerk.
    deactivated = client.get("/api/centers", params={"aktiv": "false"}).json()
    assert [c["id"] for c in deactivated["items"]] == [30]
    assert deactivated["items"][0]["aktiv"] is False
    assert deactivated["items"][0]["manuell_gepflegt"] is True


def test_manual_lock_can_be_removed(client):
    assert client.put("/api/centers/10", json=_center_payload()).json()["manuell_gepflegt"] is True

    assert client.delete("/api/centers/10/manual-lock").status_code == 204

    items = {c["id"]: c for c in client.get("/api/centers").json()["items"]}
    assert items[10]["manuell_gepflegt"] is False
    # Historie (wer/wann) bleibt als manuell_geaendert_am sichtbar.
    assert items[10]["manuell_geaendert_am"] is not None


def test_manual_lock_unknown_center_returns_404(client):
    assert client.delete("/api/centers/999/manual-lock").status_code == 404


def test_write_endpoints_validate_payload(client):
    payload = _center_payload(40)
    payload["plz"] = "123"

    assert client.post("/api/centers", json=payload).status_code == 422


@pytest.mark.parametrize(
    ("role", "write_status"),
    [("reader", 403), ("editor", 201), ("admin", 201)],
)
def test_api_enforces_roles_after_oidc_login(make_app, monkeypatch, role, write_status):
    app = make_app(**OIDC_ENV)
    from app.auth import oauth

    async def authorize_access_token(request):
        return {
            "userinfo": {
                "sub": "test-user",
                "email": "test@example.org",
                "roles": [role],
                "sid": "test-session-id",
            },
            "id_token": "test-id-token",
        }

    monkeypatch.setattr(oauth.keycloak, "authorize_access_token", authorize_access_token)

    async def mock_validate_keycloak_session(user):
        return bool(user.get("sub") and user.get("sid"))

    monkeypatch.setattr(
        "app.auth.validate_keycloak_session",
        mock_validate_keycloak_session,
    )

    with TestClient(app) as role_client:
        assert role_client.get("/auth/callback", follow_redirects=False).status_code == 307
        assert role_client.get("/api/centers").status_code == 200
        assert role_client.post("/api/centers", json=_center_payload(40)).status_code == write_status
        # Issue #85: deaktivierte Einrichtungen nur fuer editor/admin sichtbar.
        expected_aktiv_false = 200 if role in ("editor", "admin") else 403
        assert role_client.get("/api/centers", params={"aktiv": "false"}).status_code == expected_aktiv_false


@pytest.mark.parametrize(("role", "lock_status"), [("reader", 403), ("editor", 204), ("admin", 204)])
def test_manual_lock_endpoint_enforces_write_role(make_app, monkeypatch, role, lock_status):
    app = make_app(**OIDC_ENV)
    from app.auth import oauth

    async def authorize_access_token(request):
        return {
            "userinfo": {
                "sub": "test-user",
                "email": "test@example.org",
                "preferred_username": "testuser",
                "roles": [role],
                "sid": "test-session-id",
            },
            "id_token": "test-id-token",
        }

    monkeypatch.setattr(oauth.keycloak, "authorize_access_token", authorize_access_token)

    async def mock_validate_keycloak_session(user):
        return bool(user.get("sub") and user.get("sid"))

    monkeypatch.setattr("app.auth.validate_keycloak_session", mock_validate_keycloak_session)

    with TestClient(app) as role_client:
        assert role_client.get("/auth/callback", follow_redirects=False).status_code == 307
        assert role_client.delete("/api/centers/10/manual-lock").status_code == lock_status


def test_update_records_preferred_username_in_lock(make_app, monkeypatch):
    app = make_app(**OIDC_ENV)
    from app.auth import oauth

    async def authorize_access_token(request):
        return {
            "userinfo": {
                "sub": "test-user",
                "email": "test@example.org",
                "preferred_username": "mmustermann",
                "roles": ["editor"],
                "sid": "test-session-id",
            },
            "id_token": "test-id-token",
        }

    monkeypatch.setattr(oauth.keycloak, "authorize_access_token", authorize_access_token)

    async def mock_validate_keycloak_session(user):
        return bool(user.get("sub") and user.get("sid"))

    monkeypatch.setattr("app.auth.validate_keycloak_session", mock_validate_keycloak_session)

    with TestClient(app) as role_client:
        assert role_client.get("/auth/callback", follow_redirects=False).status_code == 307
        response = role_client.put("/api/centers/10", json=_center_payload())

    assert response.status_code == 200
    assert response.json()["manuell_gepflegt"] is True
    assert response.json()["manuell_geaendert_von"] == "mmustermann"
