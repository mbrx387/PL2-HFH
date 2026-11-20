"""AP5: E-Mail-Auswahl, BCC-Aufteilung, Uebergabe-Historie und Zugriffsschutz.

Laeuft wie alle Projekttests mit der SQLite-Ersatzdatenbank aus conftest.py.
Die PostgreSQL-spezifischen Pruefungen stehen in tests/test_mail_postgres.py.
"""

import json
import re
from base64 import b64encode
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, unquote, urlparse

import pytest
from fastapi.testclient import TestClient
from itsdangerous import TimestampSigner, URLSafeTimedSerializer

from app.mail_models import MailHistory
from app.mail_service import (
    MailtoTooLongError,
    Recipient,
    build_mailto_url,
    collect_recipients,
    normalize_email,
    split_email_field,
    split_recipients,
)

SQL_FILE = Path(__file__).parent.parent / "db" / "init" / "002_create_mail_history.sql"
OIDC_ENV = {
    "AUTH_ENABLED": "true",
    "OIDC_ISSUER": "http://kc.test/idp/realms/hfh-pflege",
    "OIDC_CLIENT_ID": "pflege-finder",
    "OIDC_CLIENT_SECRET": "s3cret-but-not-a-placeholder",
}


def _prepare(client, **body):
    response = client.post("/api/mail/prepare", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def _handoff(client, token):
    return client.post("/api/mail/handoff", json={"handoff_token": token})


def _query(url):
    return parse_qs(urlparse(url).query)


def _add_centers(rows):
    from app.database import SessionLocal
    from app.models import Center

    with SessionLocal() as db:
        db.add_all(Center(**row) for row in rows)
        db.commit()


# --- Adressen aus der Datenbank -------------------------------------------


def test_normalize_single_address():
    assert normalize_email(" a@example.org ") == "a@example.org"
    for value in ("", "wrong", "a@@b.org", "a b@example.org", "a@x..org", "a@example", "<a@example.org>"):
        assert normalize_email(value) is None, value


def test_field_with_several_addresses_is_split():
    # Format wie in app/data/pflegestellen.csv (rund 15 % der Felder).
    valid, invalid = split_email_field("a@x.de; b@x.de;c@y.de , kaputt@ ; ")
    assert valid == ["a@x.de", "b@x.de", "c@y.de"]
    assert invalid == 1


def test_collect_recipients_counts_and_deduplicates():
    centers = [
        SimpleNamespace(id=1, email="Info@example.org", bundesland="SN"),
        SimpleNamespace(id=2, email="info@example.org; team@example.org", bundesland="BY "),
        SimpleNamespace(id=3, email="", bundesland="SN"),
        SimpleNamespace(id=4, email="kaputt", bundesland="SN"),
    ]
    result = collect_recipients(centers)
    assert [(r.center_id, r.email, r.bundesland) for r in result.recipients] == [
        (1, "Info@example.org", "SN"),
        (2, "team@example.org", "BY"),
    ]
    assert result.reached_centers == 2
    assert result.duplicate_emails == 1
    assert result.centers_without_email == 1
    assert result.centers_without_valid_email == 1
    assert result.invalid_addresses == 1


# --- mailto:-Link und BCC-Aufteilung --------------------------------------


def test_mailto_uses_only_bcc_and_rfc6068_line_breaks():
    url = build_mailto_url(["one@example.org", "two@example.org"], "Hallo & Welt?", "Zeile 1\nZeile 2")
    assert url.startswith("mailto:?bcc=one@example.org,two@example.org&")
    q = _query(url)
    assert q == {
        "bcc": ["one@example.org,two@example.org"],
        "subject": ["Hallo & Welt?"],
        "body": ["Zeile 1\r\nZeile 2"],
    }
    assert "%0D%0A" in url
    assert not urlparse(url).path  # kein "to"-Empfaenger


def test_mailto_encodes_special_characters_in_addresses():
    url = build_mailto_url(["a+b&c@example.org"], "x", "")
    assert "a%2Bb%26c@example.org" in url
    assert _query(url)["bcc"] == ["a+b&c@example.org"]


@pytest.mark.parametrize(
    ("size", "expected"),
    [(1, [1]), (19, [19]), (20, [20]), (21, [20, 1]), (40, [20, 20]), (41, [20, 20, 1]),
     (500, [20] * 25), (137, [20] * 6 + [17])],
)
def test_batch_boundaries(size, expected):
    recipients = [Recipient(i, f"u{i}@x.org") for i in range(1, size + 1)]
    batches = split_recipients(recipients, subject="Test", body="", max_recipients=20, max_mailto_length=5000)
    assert [len(batch) for batch in batches] == expected


def test_long_links_are_split_without_losing_recipients():
    recipients = [Recipient(i, f"very-long-email-address-{i}@example.org") for i in range(40)]
    batches = split_recipients(recipients, subject="Test", body="", max_recipients=20, max_mailto_length=260)
    assert len(batches) > 2
    assert [r for batch in batches for r in batch] == recipients
    assert all(len(build_mailto_url([r.email for r in batch], "Test", "")) <= 260 for batch in batches)


def test_too_long_text_fails_cleanly():
    with pytest.raises(MailtoTooLongError):
        split_recipients(
            [Recipient(1, "a@example.org")], subject="Test", body="x" * 300,
            max_recipients=20, max_mailto_length=256,
        )


# --- POST /api/mail/prepare -----------------------------------------------


def test_prepare_by_ids_deduplicates_and_skips_centers_without_email(client):
    data = _prepare(client, center_ids=[10, 20, 10, 30], subject="Anfrage", body="Hallo")
    assert data["selected_centers"] == 3
    assert data["reached_centers"] == 2
    assert data["centers_without_email"] == 1
    assert data["recipient_count"] == 2
    assert data["batch_count"] == 1
    assert data["batches"][0]["bundeslaender"] == ["BY", "SN"]
    # Vorbereiten allein schreibt KEINE Historie.
    assert client.get("/api/mail-history").json()["total"] == 0


def test_prepare_by_filter_matches_center_list(client):
    data = _prepare(client, filters={"bundesland": "sn", "angebot": "pflegeberatung"})
    listed = client.get("/api/centers", params={"bundesland": "sn", "angebot": "pflegeberatung"}).json()
    assert data["selected_centers"] == listed["total"] == 1
    assert data["recipient_count"] == 1


def test_filter_selection_is_not_limited_to_the_200_visible_centers(client):
    def email(i):
        return f"zentrum{i}@example.org; vertretung{i}@example.org" if i % 10 == 0 else f"z{i}@example.org"

    _add_centers(
        dict(id=1000 + i, name=f"Zentrum {i}", plz="20000", ort="Hamburg", bundesland="HH", email=email(i))
        for i in range(550)
    )
    data = _prepare(client, filters={"bundesland": "HH"})
    assert data["selected_centers"] == 550
    assert data["recipient_count"] == 550 + 55  # jede 10. Einrichtung hat zwei Adressen
    assert sum(b["recipient_count"] for b in data["batches"]) == data["recipient_count"]
    assert all(1 <= b["recipient_count"] <= 20 for b in data["batches"])
    assert [b["number"] for b in data["batches"]] == list(range(1, data["batch_count"] + 1))


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"filters": {}},
        {"center_ids": []},
        {"center_ids": [0]},
        {"center_ids": [10], "filters": {"bundesland": "SN"}},
        {"center_ids": [10], "subject": "   "},
        {"center_ids": [10], "subject": "Zeile\nZwei"},
        {"center_ids": [10], "emails": ["fremd@example.org"]},  # Adressen nie vom Browser
        {"filters": {"angebot": "unbekannt"}},
    ],
)
def test_prepare_rejects_invalid_requests(client, body):
    assert client.post("/api/mail/prepare", json=body).status_code == 422


def test_prepare_rejects_unknown_ids(client):
    res = client.post("/api/mail/prepare", json={"center_ids": [999999]})
    assert res.status_code == 422
    assert "Unbekannte" in res.json()["detail"]


def test_prepare_rejects_selection_without_any_address(client):
    res = client.post("/api/mail/prepare", json={"center_ids": [20]})
    assert res.status_code == 422


def test_prepare_rejects_text_that_does_not_fit_into_mailto(client):
    assert client.post("/api/mail/prepare", json={"center_ids": [10], "body": "y" * 4000}).status_code == 422


# --- POST /api/mail/handoff und Historie ----------------------------------


def test_handoff_writes_history_and_returns_bcc_link(client):
    prepared = _prepare(client, center_ids=[10, 30], subject="Anfrage", body="Hallo\nWelt")
    response = _handoff(client, prepared["batches"][0]["handoff_token"])
    assert response.status_code == 200, response.text
    data = response.json()
    entry = data["history"]
    assert entry["status"] == "handoff_attempted"
    assert entry["recipient_count"] == 2
    assert entry["recipients"] == ["dresden@example.org", "muenchen@example.org"]
    assert entry["subject"] == "Anfrage"
    assert entry["body"] == "Hallo\nWelt"
    assert entry["campaign_id"] == prepared["campaign_id"]
    assert (entry["batch_number"], entry["batch_count"]) == (1, 1)
    assert entry["bundeslaender"] == ["BY", "SN"]
    assert entry["created_by"] is None  # lokal ohne Login
    assert set(_query(data["mailto_url"])) == {"bcc", "subject", "body"}
    assert client.get("/api/mail-history").json()["total"] == 1


def test_each_batch_is_logged_separately_with_its_number(client):
    _add_centers(
        dict(id=2000 + i, name=f"B {i}", plz="10115", ort="Berlin", bundesland="BE",
             email=f"b{i}@example.org")
        for i in range(45)
    )
    prepared = _prepare(client, filters={"bundesland": "BE"}, subject="Rundmail")
    assert prepared["batch_count"] == 3
    for batch in prepared["batches"]:
        assert _handoff(client, batch["handoff_token"]).status_code == 200
    items = client.get("/api/mail-history", params={"campaign_id": prepared["campaign_id"]}).json()["items"]
    assert sorted((i["batch_number"], i["recipient_count"]) for i in items) == [(1, 20), (2, 20), (3, 5)]


def test_same_token_creates_only_one_history_entry(client):
    token = _prepare(client, center_ids=[10])["batches"][0]["handoff_token"]
    first, second = _handoff(client, token), _handoff(client, token)
    assert first.status_code == second.status_code == 200
    assert first.json()["history"]["id"] == second.json()["history"]["id"]
    assert client.get("/api/mail-history").json()["total"] == 1


def test_handoff_rejects_tampered_forged_or_extended_requests(client):
    token = _prepare(client, center_ids=[10], subject="Original")["batches"][0]["handoff_token"]
    damaged = token[:-2] + ("AA" if not token.endswith("AA") else "BB")
    forged = URLSafeTimedSerializer("falscher-schluessel", salt="ap5-mail-handoff-v2").dumps(
        {"id": "a" * 32, "campaign": "b" * 32, "number": 1, "count": 1, "emails": ["x@example.org"],
         "laender": [], "subject": "Fake", "body": ""}
    )
    assert _handoff(client, damaged).status_code == 422
    assert _handoff(client, forged).status_code == 422
    extended = client.post("/api/mail/handoff", json={"handoff_token": token, "subject": "Fake"})
    assert extended.status_code == 422
    assert client.get("/api/mail-history").json()["total"] == 0


def test_history_is_sorted_paginated_and_filterable(client):
    for subject, body in (("Erste Anfrage", "Text A"), ("Zweite", "Rueckfrage zu 100%")):
        token = _prepare(client, center_ids=[10], subject=subject, body=body)["batches"][0]["handoff_token"]
        assert _handoff(client, token).status_code == 200
    history = client.get("/api/mail-history").json()
    assert history["total"] == 2
    assert [item["subject"] for item in history["items"]] == ["Zweite", "Erste Anfrage"]
    assert len(client.get("/api/mail-history", params={"limit": 1, "offset": 1}).json()["items"]) == 1
    assert client.get("/api/mail-history", params={"search": "100%"}).json()["total"] == 1
    assert client.get("/api/mail-history", params={"search": "erste"}).json()["total"] == 1
    year = int(history["items"][0]["created_at"][:4])
    month = int(history["items"][0]["created_at"][5:7])
    assert client.get("/api/mail-history", params={"year": year}).json()["total"] == 2
    assert client.get("/api/mail-history", params={"year": year, "month": month}).json()["total"] == 2
    assert client.get("/api/mail-history", params={"year": year - 1}).json()["total"] == 0
    assert client.get("/api/mail-history", params={"month": 1}).status_code == 422
    assert client.get("/api/mail-history", params={"limit": 201}).status_code == 422


# --- Zugriffsschutz (Keycloak-Login) --------------------------------------


def _session_cookie(secret: str, user: dict) -> str:
    """Erzeugt ein Session-Cookie wie Starlette nach einem erfolgreichen Login."""
    data = b64encode(json.dumps({"user": user}).encode("utf-8"))
    return TimestampSigner(secret).sign(data).decode("utf-8")


def test_mail_endpoints_require_login(make_app):
    app = make_app(**OIDC_ENV)
    with TestClient(app) as client:
        for method, path in (
            ("post", "/api/mail/prepare"),
            ("post", "/api/mail/handoff"),
            ("get", "/api/mail-history"),
        ):
            res = getattr(client, method)(path, follow_redirects=False)
            assert res.status_code == 307, path
            assert res.headers["location"].startswith("/auth/login?next=")


def test_logged_in_user_is_recorded_as_sender(make_app):
    app = make_app(**OIDC_ENV)
    with TestClient(app) as client:
        client.cookies.set("session", _session_cookie("x" * 40, {"sub": "123", "email": "adrian@hfh.test"}))
        token = _prepare(client, center_ids=[10])["batches"][0]["handoff_token"]
        entry = _handoff(client, token).json()["history"]
        assert entry["created_by"] == "adrian@hfh.test"


# --- Datenbankschema -------------------------------------------------------


def test_sql_init_file_matches_orm_model():
    """db/init/002 (frische Volumes) und das ORM (bestehende DB) muessen gleich sein."""
    sql = SQL_FILE.read_text(encoding="utf-8")
    body = sql[sql.index("CREATE TABLE IF NOT EXISTS mail_history (") :].split(");", 1)[0]
    # Spaltenzeilen beginnen klein geschrieben; CONSTRAINT-Zeilen gross.
    columns = {match.group(1) for match in re.finditer(r"^\s{4}([a-z_]+)\s", body, flags=re.MULTILINE)}
    assert columns == set(MailHistory.__table__.columns.keys())
    for constraint in MailHistory.__table__.constraints:
        if constraint.name and not constraint.name.endswith("_pkey"):
            assert constraint.name in sql, constraint.name
    for index in MailHistory.__table__.indexes:
        assert index.name in sql, index.name


def test_ensure_table_is_idempotent_and_detects_outdated_schema(client):
    import app.database as database
    from app.mail_models import ensure_mail_history_table

    ensure_mail_history_table(database.engine)  # Tabelle existiert schon: nichts passiert
    with database.engine.begin() as connection:
        connection.exec_driver_sql("DROP TABLE mail_history")
        connection.exec_driver_sql("CREATE TABLE mail_history (id INTEGER PRIMARY KEY, subject TEXT)")
    with pytest.raises(RuntimeError, match="veraltetes Schema"):
        ensure_mail_history_table(database.engine)


def test_umlauts_in_subject_survive_the_link():
    url = build_mailto_url(["a@example.org"], "Ä Ö Ü ß", "")
    assert unquote(url.split("subject=")[1]) == "Ä Ö Ü ß"
