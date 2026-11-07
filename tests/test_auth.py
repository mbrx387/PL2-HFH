import asyncio
import json
from pathlib import Path

import pytest
from fastapi import HTTPException, Request
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


def test_keycloak_app_roles_are_allowlisted(make_app):
    make_app()
    from app.auth import extract_app_roles

    assert extract_app_roles({"roles": ["reader", "admin", "unknown", 7]}) == ["admin", "reader"]
    assert extract_app_roles({"roles": "admin"}) == []


@pytest.mark.parametrize(
    ("role", "permission", "expected"),
    [
        ("reader", "read_centers", True),
        ("reader", "write_centers", False),
        ("editor", "read_centers", True),
        ("editor", "write_centers", True),
        ("admin", "read_centers", True),
        ("admin", "write_centers", True),
    ],
)
def test_role_permission_matrix(make_app, role, permission, expected):
    make_app()
    from app.auth import has_permission

    assert has_permission({"roles": [role]}, permission) is expected


def test_permission_dependency_rejects_reader_write(make_app):
    make_app(**OIDC_ENV)
    from app.auth import require_permission

    check_write = require_permission("write_centers")
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/centers",
            "headers": [],
            "session": {"user": {"roles": ["reader"]}},
        }
    )
    with pytest.raises(HTTPException) as error:
        asyncio.run(check_write(request))
    assert error.value.status_code == 403


def test_keycloak_realm_maps_client_roles_to_oidc_claim():
    realm_path = Path(__file__).parents[1] / "keycloak" / "realm-export.json"
    realm = json.loads(realm_path.read_text(encoding="utf-8"))
    client = next(item for item in realm["clients"] if item["clientId"] == "pflege-finder")
    mapper = next(item for item in client["protocolMappers"] if item["name"] == "application-roles")
    demo = next(user for user in realm["users"] if user["username"] == "demo")

    assert {role["name"] for role in client["roles"]} == {"reader", "editor", "admin"}
    assert mapper["config"]["claim.name"] == "roles"
    assert mapper["config"]["id.token.claim"] == "true"
    assert mapper["config"]["userinfo.token.claim"] == "true"
    assert demo["clientRoles"]["pflege-finder"] == ["reader"]
