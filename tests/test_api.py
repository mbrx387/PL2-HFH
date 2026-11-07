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
    response = client.post("/api/centers", json=_center_payload(40))

    assert response.status_code == 201
    assert response.json()["id"] == 40
    assert response.json()["bundesland"] == "SN"
    assert response.json()["leistungen"] == "Pflegeberatung"


def test_create_center_rejects_unknown_service(client):
    payload = _center_payload(40)
    payload["services"] = ["Unknown"]

    assert client.post("/api/centers", json=payload).status_code == 422


def test_create_center_conflicting_id_returns_conflict(client):
    assert client.post("/api/centers", json=_center_payload(10)).status_code == 409


def test_update_center_replaces_data_and_services(client):
    response = client.put("/api/centers/10", json=_center_payload())

    assert response.status_code == 200
    assert response.json()["name"] == "Neue Beratungsstelle"
    assert response.json()["leistungen"] == "Pflegeberatung"


def test_update_center_returns_not_found(client):
    assert client.put("/api/centers/999", json=_center_payload()).status_code == 404


def test_delete_center(client):
    response = client.delete("/api/centers/30")

    assert response.status_code == 204
    assert client.get("/api/centers").json()["total"] == 2
    assert client.get("/api/bundeslaender").json() == ["SN"]
    assert client.put("/api/centers/30", json=_center_payload()).status_code == 200
    assert client.get("/api/centers").json()["total"] == 3


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
            "userinfo": {"sub": "test-user", "email": "test@example.org", "roles": [role]},
            "id_token": "test-id-token",
        }

    monkeypatch.setattr(oauth.keycloak, "authorize_access_token", authorize_access_token)

    with TestClient(app) as role_client:
        assert role_client.get("/auth/callback", follow_redirects=False).status_code == 307
        assert role_client.get("/api/centers").status_code == 200
        assert role_client.post("/api/centers", json=_center_payload(40)).status_code == write_status
