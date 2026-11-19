"""Fixtures fuer die Playwright-E2E-Tests.

- Sicherheitspruefung: der Lauf bricht ab, bevor irgendetwas passiert, wenn
  Datenbank oder App nicht eindeutig lokale Testinstanzen sind.
- app_server: startet die App (e2e/run_app.py), sofern E2E_BASE_URL nicht
  gesetzt ist (in CI startet der Workflow die App selbst).
- reset_db: vor JEDEM Test derselbe Datenbestand (e2e/data/centers.csv).
"""
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest
from db_seed import reset_database
from playwright.sync_api import Page
from run_app import base_url as configured_base_url
from run_app import database_url, safety_problems

E2E_DIR = Path(__file__).resolve().parent
REPO_ROOT = E2E_DIR.parent
SEED_CSV = E2E_DIR / "data" / "centers.csv"
APP_LOG = REPO_ROOT / "build" / "e2e-app.log"
STARTUP_TIMEOUT_S = 30

# Anzahl Datensaetze in e2e/data/centers.csv - Tests beziehen sich darauf.
SEED_COUNT = 6


def pytest_sessionstart(session):
    problems = safety_problems()
    if problems:
        pytest.exit(
            "E2E-Tests abgebrochen (Schutz vor Nicht-Testumgebungen):\n  - " + "\n  - ".join(problems),
            returncode=2,
        )


def _is_healthy(url: str) -> bool:
    try:
        with urllib.request.urlopen(f"{url}/healthz", timeout=2) as res:
            return res.status == 200
    except (urllib.error.URLError, OSError):
        return False


def _wait_until_healthy(url: str, timeout_s: float, proc: subprocess.Popen | None = None) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if _is_healthy(url):
            return
        if proc is not None and proc.poll() is not None:
            break
        time.sleep(0.5)
    hint = f" App-Log: {APP_LOG}" if proc is not None else ""
    raise RuntimeError(f"App unter {url} nicht erreichbar (/healthz).{hint}")


@pytest.fixture(scope="session")
def app_server():
    url = configured_base_url()
    if os.environ.get("E2E_BASE_URL"):
        # Extern gestartet (z. B. GitHub Actions) - nur pruefen.
        _wait_until_healthy(url, STARTUP_TIMEOUT_S)
        yield url
        return

    if _is_healthy(url):
        pytest.exit(
            f"Unter {url} laeuft bereits ein Server. Beenden oder E2E_BASE_URL setzen, "
            "wenn er bewusst verwendet werden soll.",
            returncode=2,
        )

    APP_LOG.parent.mkdir(parents=True, exist_ok=True)
    with APP_LOG.open("w", encoding="utf-8") as log:
        proc = subprocess.Popen(
            [sys.executable, str(E2E_DIR / "run_app.py")],
            cwd=REPO_ROOT,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            _wait_until_healthy(url, STARTUP_TIMEOUT_S, proc)
            yield url
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()


@pytest.fixture(scope="session")
def base_url(app_server):
    """Ueberschreibt das base_url-Fixture von pytest-base-url/pytest-playwright.

    Damit funktionieren relative Pfade wie page.goto("/") und die App laeuft
    garantiert, bevor der erste Browser-Kontext entsteht.
    """
    return app_server


@pytest.fixture(autouse=True)
def reset_db():
    """Definierter Ausgangszustand vor jedem einzelnen Test."""
    reset_database(database_url(), SEED_CSV)


@pytest.fixture
def console_errors(page: Page) -> list[str]:
    """Sammelt Konsolenfehler und unbehandelte JS-Fehler (inkl. CSP-Verstoesse)."""
    errors: list[str] = []
    page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    return errors
