import pytest
from fastapi.testclient import TestClient

OIDC_ENV = {
    "AUTH_ENABLED": "true",
    "OIDC_ISSUER": "http://kc.test/idp/realms/hfh-pflege",
    "OIDC_CLIENT_ID": "pflege-finder",
    "OIDC_CLIENT_SECRET": "s3cret-but-not-a-placeholder",
}


def test_app_refuses_to_start_without_oidc(make_app):
    app = make_app(AUTH_ENABLED="true")
    with pytest.raises(RuntimeError, match="OIDC"):
        with TestClient(app):
            pass


@pytest.mark.parametrize("secret", ["change-me", "insecure-dev-secret-change-me", "short"])
def test_app_refuses_weak_secret_in_production(make_app, secret):
    app = make_app(ENVIRONMENT="production", SECRET_KEY=secret)
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        with TestClient(app):
            pass


def test_placeholder_client_secret_counts_as_unconfigured(make_app):
    app = make_app(**{**OIDC_ENV, "OIDC_CLIENT_SECRET": "change-me"})
    with pytest.raises(RuntimeError, match="OIDC"):
        with TestClient(app):
            pass


def test_protected_routes_redirect_to_login(make_app):
    app = make_app(**OIDC_ENV)
    with TestClient(app) as client:
        for path in ("/", "/api/centers", "/api/docs"):
            res = client.get(path, follow_redirects=False)
            assert res.status_code == 307, path
            assert res.headers["location"].startswith("/auth/login?next=")
        assert client.get("/healthz").status_code == 200


def test_login_redirects_to_keycloak_and_rejects_open_redirect(make_app):
    app = make_app(**OIDC_ENV)
    with TestClient(app) as client:
        res = client.get("/auth/login", params={"next": "https://evil.example"}, follow_redirects=False)
        assert res.status_code == 302
        assert res.headers["location"].startswith(OIDC_ENV["OIDC_ISSUER"] + "/protocol/openid-connect/auth")
