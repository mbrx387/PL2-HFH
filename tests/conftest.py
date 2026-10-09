"""Baut die FastAPI-App mit kontrollierten Umgebungsvariablen neu auf.

Settings werden in app.config/app.auth/app.main auf Modulebene gelesen, daher
muessen diese Module nach dem Setzen der Env-Variablen neu geladen werden.
"""
import importlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

TEST_CSV = str(Path(__file__).parent / "data" / "centers.csv")

BASE_ENV = {
    "ENVIRONMENT": "development",
    "AUTH_ENABLED": "false",
    "DATA_FILE": TEST_CSV,
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

    config.get_settings.cache_clear()
    import app.auth as auth
    import app.main as main

    importlib.reload(config)
    importlib.reload(auth)
    importlib.reload(main)
    return main.app


@pytest.fixture
def make_app(monkeypatch):
    return lambda **overrides: _build_app(monkeypatch, **overrides)


@pytest.fixture
def client(make_app):
    with TestClient(make_app()) as c:
        yield c
