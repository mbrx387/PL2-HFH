"""Startet die App fuer die E2E-Tests mit fest definierter Testkonfiguration.

Eine Quelle fuer die Test-Umgebung: e2e/conftest.py startet dieses Skript
lokal automatisch, der GitHub-Actions-Workflow ruft es direkt auf.

    python e2e/run_app.py

Alle relevanten Variablen werden explizit gesetzt und ueberstimmen damit eine
evtl. vorhandene lokale .env (pydantic-settings: Umgebung vor .env) - die App
kann so nicht versehentlich mit Produktivwerten starten.
"""
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

REPO_ROOT = Path(__file__).resolve().parent.parent

APP_HOST = "127.0.0.1"
APP_PORT = 8800
DEFAULT_BASE_URL = f"http://{APP_HOST}:{APP_PORT}"
# connect_timeout: ohne erreichbare DB sofort mit klarem Fehler abbrechen statt
# endlos zu warten (Docker Desktop nimmt Verbindungen auch bei gestopptem Container an).
DEFAULT_DATABASE_URL = "postgresql://pl2:e2e@127.0.0.1:55432/pflegedb_e2e?connect_timeout=5"

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
REQUIRED_DB_SUFFIX = "_e2e"


def base_url() -> str:
    return os.environ.get("E2E_BASE_URL", DEFAULT_BASE_URL).rstrip("/")


def database_url() -> str:
    """libpq-URL der Test-Datenbank (fuer psycopg)."""
    return os.environ.get("E2E_DATABASE_URL", DEFAULT_DATABASE_URL)


def safety_problems() -> list[str]:
    """Gruende, warum der Lauf NICHT starten darf (leer = alles in Ordnung)."""
    problems = []
    db = urlsplit(database_url())
    db_name = db.path.lstrip("/")
    if db.hostname not in LOCAL_HOSTS:
        problems.append(f"E2E_DATABASE_URL zeigt nicht auf localhost (Host: {db.hostname!r}).")
    if not db_name.endswith(REQUIRED_DB_SUFFIX):
        problems.append(f"Datenbankname {db_name!r} endet nicht auf {REQUIRED_DB_SUFFIX!r}.")
    if os.environ.get("ENVIRONMENT", "").strip().lower() == "production":
        problems.append("ENVIRONMENT=production ist gesetzt.")
    if urlsplit(base_url()).hostname not in LOCAL_HOSTS:
        problems.append(f"E2E_BASE_URL ist nicht lokal ({base_url()!r}).")
    return problems


def app_env() -> dict[str, str]:
    """Umgebungsvariablen der Test-App (Phase 1: ohne Login)."""
    sqlalchemy_url = database_url().replace("postgresql://", "postgresql+psycopg://", 1)
    return {
        "ENVIRONMENT": "development",
        "LOG_LEVEL": "info",
        "DATABASE_URL": sqlalchemy_url,
        "SECRET_KEY": "e2e-only-secret-key-not-used-anywhere-else",
        "ALLOWED_ORIGINS": base_url(),
        "AUTH_ENABLED": "false",
        "OIDC_ISSUER": "",
        "OIDC_CLIENT_ID": "",
        "OIDC_CLIENT_SECRET": "",
        "OIDC_ISSUER_INTERNAL": "",
    }


def main() -> None:
    problems = safety_problems()
    if problems:
        sys.exit("E2E-App wird nicht gestartet:\n  - " + "\n  - ".join(problems))

    os.environ.update(app_env())
    # app/static und app/templates werden relativ zum Arbeitsverzeichnis geladen.
    os.chdir(REPO_ROOT)
    sys.path.insert(0, str(REPO_ROOT))

    import uvicorn

    # Port aus E2E_BASE_URL, damit App und Tests dieselbe Adresse nutzen; der
    # Host bleibt fest lokal.
    port = urlsplit(base_url()).port or APP_PORT
    uvicorn.run("app.main:app", host=APP_HOST, port=port, log_level="info")


if __name__ == "__main__":
    main()
