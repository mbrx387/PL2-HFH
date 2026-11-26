import pytest
from fastapi.testclient import TestClient


@pytest.mark.parametrize("enabled", [False, True])
def test_admin_switch(make_app, monkeypatch, enabled):
    app = make_app(
        AUTH_ENABLED="true",
        OIDC_ISSUER="https://example.org/idp/realms/hfh-pflege",
        OIDC_CLIENT_ID="pflege-finder",
        OIDC_CLIENT_SECRET="test-login-secret",
        KEYCLOAK_ADMIN_ENABLED=str(enabled).lower(),
        KEYCLOAK_ADMIN_CLIENT_SECRET="test-admin-secret",
    )
    from app.auth import oauth

    async def login(request):
        return {"userinfo": {"sub": "u", "sid": "s", "roles": ["admin"]}}

    calls = []

    async def validate(user):
        calls.append(user)
        return True

    monkeypatch.setattr(oauth.keycloak, "authorize_access_token", login)
    monkeypatch.setattr("app.auth.validate_keycloak_session", validate)
    with TestClient(app) as client:
        assert client.get("/auth/callback", follow_redirects=False).status_code == 307
        page = client.get("/")
        assert page.status_code == 200
        assert ('data-can-manage-users="true"' in page.text) is enabled
        assert bool(calls) is enabled
        assert 'href="https://example.org/idp/realms/hfh-pflege/account/"' in page.text
        assert any(r.path == "/api/admin/users" for r in app.routes) is enabled
        if not enabled:
            assert client.get("/api/admin/users").status_code == 404
