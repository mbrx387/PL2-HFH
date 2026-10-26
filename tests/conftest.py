"""Baut die FastAPI-App mit kontrollierten Umgebungsvariablen neu auf.

Settings und der DB-Engine werden vor App-Start konfiguriert, weil die App ihre
Konfiguration auf Modulebene liest. Jede Test-App erhält eine frische SQLite-DB.
"""
import csv
import importlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

TEST_CSV = str(Path(__file__).parent / "data" / "centers.csv")

BASE_ENV = {
    "ENVIRONMENT": "development",
    "AUTH_ENABLED": "false",
    "DATABASE_URL": "sqlite://",
    "SECRET_KEY": "x" * 40,
    "OIDC_ISSUER": "",
    "OIDC_CLIENT_ID": "",
    "OIDC_CLIENT_SECRET": "",
}


def _build_app(monkeypatch: pytest.MonkeyPatch, **overrides: str):
    for key, value in {**BASE_ENV, **overrides}.items():
        monkeypatch.setenv(key, value)
    # Projektroot als CWD (fuer app/static, app/templates); .env wird durch
    # die gesetzten Env-Variablen ueberstimmt.
    monkeypatch.chdir(Path(__file__).parent.parent)

    import app.config as config

    importlib.reload(config)
    config.get_settings.cache_clear()
    import app.database as database

    database.configure_database("sqlite://")
    import app.auth as auth
    import app.main as main

    importlib.reload(auth)
    importlib.reload(main)

    from app.models import Center, Service

    database.Base.metadata.drop_all(bind=database.engine)
    database.Base.metadata.create_all(bind=database.engine)
    with database.SessionLocal() as db:
        with Path(TEST_CSV).open(encoding="utf-8", newline="") as source:
            records = list(csv.DictReader(source, delimiter=";"))
        service_names = {
            "pflegestuetzpunkt": "Pflegestützpunkt",
            "pflegeberatung": "Pflegeberatung",
            "wohnberatung": "Wohnberatung",
            "demenzberatung": "Demenzberatung",
            "angehoerigenberatung": "Angehörigenberatung",
            "betreuungsberatung": "Betreuungsberatung",
        }
        offered = set()
        for record in records:
            offered.update(
                label for field, label in service_names.items() if record[field] == "1"
            )
            offered.update(value.strip() for value in record["leistungen"].split(",") if value.strip())
        services = {name: Service(name=name) for name in offered}
        db.add_all(services.values())
        db.flush()
        for record in records:
            names = {
                label for field, label in service_names.items() if record[field] == "1"
            }
            names.update(value.strip() for value in record["leistungen"].split(",") if value.strip())
            db.add(
                Center(
                    id=int(record["unsere_id"]),
                    zqp_id=record["zqp_id"] or None,
                    name=record["name"],
                    adresse=record["adresse"],
                    plz=record["plz"],
                    ort=record["ort"],
                    bundesland=record["bundesland"],
                    email=record["email"],
                    telefon=record["telefon"],
                    website=record["website"],
                    latitude=float(record["latitude"]) if record["latitude"] else None,
                    longitude=float(record["longitude"]) if record["longitude"] else None,
                    services=[services[name] for name in names],
                )
            )
        db.commit()
    return main.app


@pytest.fixture
def make_app(monkeypatch):
    return lambda **overrides: _build_app(monkeypatch, **overrides)


@pytest.fixture
def client(make_app):
    with TestClient(make_app()) as c:
        yield c
