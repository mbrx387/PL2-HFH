"""Baut die FastAPI-App mit kontrollierten Umgebungsvariablen neu auf.

Settings werden in app.config/app.auth/app.main auf Modulebene gelesen, daher
muessen diese Module nach dem Setzen der Env-Variablen neu geladen werden.
"""
import csv
import importlib
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

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


def _prepare_test_database() -> None:
    from app.database import Base, SessionLocal, engine
    from app.models import Center, Service, center_services

    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        db.execute(delete(center_services))
        db.execute(delete(Center))
        db.execute(delete(Service))

        with Path(TEST_CSV).open(newline="", encoding="utf-8-sig") as csv_file:
            rows = list(csv.DictReader(csv_file, delimiter=";"))

        service_names = {
            name
            for row in rows
            for name, column in (
                ("Pflegestützpunkt", "pflegestuetzpunkt"),
                ("Pflegeberatung", "pflegeberatung"),
                ("Wohnberatung", "wohnberatung"),
                ("Demenzberatung", "demenzberatung"),
                ("Angehörigenberatung", "angehoerigenberatung"),
                ("Betreuungsberatung", "betreuungsberatung"),
            )
            if row[column] == "1"
        }
        service_names.update(row["leistungen"].strip() for row in rows if row["leistungen"].strip())
        services = {name: Service(name=name) for name in service_names}
        db.add_all(services.values())
        db.flush()

        for row in rows:
            offered_names = {
                name
                for name, column in (
                    ("Pflegestützpunkt", "pflegestuetzpunkt"),
                    ("Pflegeberatung", "pflegeberatung"),
                    ("Wohnberatung", "wohnberatung"),
                    ("Demenzberatung", "demenzberatung"),
                    ("Angehörigenberatung", "angehoerigenberatung"),
                    ("Betreuungsberatung", "betreuungsberatung"),
                )
                if row[column] == "1"
            }
            if row["leistungen"].strip():
                offered_names.add(row["leistungen"].strip())
            offered = [services[name] for name in offered_names]
            db.add(
                Center(
                    id=int(row["unsere_id"]),
                    zqp_id=row["zqp_id"],
                    name=row["name"],
                    adresse=row["adresse"],
                    plz=row["plz"],
                    ort=row["ort"],
                    bundesland=row["bundesland"],
                    email=row["email"],
                    telefon=row["telefon"],
                    website=row["website"],
                    latitude=float(row["latitude"]) if row["latitude"] else None,
                    longitude=float(row["longitude"]) if row["longitude"] else None,
                    quelle_updated_at=datetime.fromisoformat(row["updated_at"]),
                    services=offered,
                )
            )
        db.commit()


def _build_app(monkeypatch: pytest.MonkeyPatch, **overrides: str):
    for key, value in {**BASE_ENV, **overrides}.items():
        monkeypatch.setenv(key, value)
    # Projektroot als CWD (fuer app/static, app/templates); .env wird durch
    # die gesetzten Env-Variablen ueberstimmt.
    monkeypatch.chdir(Path(__file__).parent.parent)

    import app.config as config

    config.get_settings.cache_clear()
    import app.auth as auth
    import app.main as main

    importlib.reload(config)
    importlib.reload(auth)
    importlib.reload(main)
    _prepare_test_database()
    return main.app


@pytest.fixture
def make_app(monkeypatch):
    return lambda **overrides: _build_app(monkeypatch, **overrides)


@pytest.fixture
def client(make_app):
    with TestClient(make_app()) as c:
        yield c
