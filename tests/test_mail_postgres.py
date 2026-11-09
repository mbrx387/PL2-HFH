"""AP5: Pruefungen gegen ein ECHTES PostgreSQL (optional, in der CI uebersprungen).

Aktivieren nur mit einer WEGWERF-Testdatenbank, niemals mit Produktivdaten:

    AP5_TEST_POSTGRES_URL=postgresql+psycopg://pl2:PASSWORT@localhost:5432/pflegedb_test pytest -q

Schutz: Der Datenbankname muss "test" enthalten. Jeder Test arbeitet in einem
eigenen, zufaellig benannten Schema, das am Ende wieder geloescht wird.
"""

import os
import threading
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, make_url, text
from sqlalchemy.exc import IntegrityError

from app.mail_models import MailHistory, ensure_mail_history_table

URL = os.environ.get("AP5_TEST_POSTGRES_URL")
ROOT = Path(__file__).parent.parent

pytestmark = pytest.mark.skipif(not URL, reason="AP5_TEST_POSTGRES_URL nicht gesetzt")


@pytest.fixture
def schema():
    if "test" not in (make_url(URL).database or ""):
        pytest.fail("Sicherheitsstopp: AP5_TEST_POSTGRES_URL muss auf eine *test*-Datenbank zeigen.")
    name = f"ap5_test_{uuid.uuid4().hex[:10]}"
    admin = create_engine(URL)
    with admin.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{name}"')
    try:
        yield name
    finally:
        with admin.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{name}" CASCADE')
        admin.dispose()


def _engine(schema_name: str):
    return create_engine(URL, connect_args={"options": f"-csearch_path={schema_name}"})


def _run_sql_file(engine, relative_path: str) -> None:
    raw = engine.raw_connection()
    try:
        with raw.cursor() as cursor:
            cursor.execute((ROOT / relative_path).read_text(encoding="utf-8"))
        raw.commit()
    finally:
        raw.close()


def _describe(engine, schema_name: str) -> dict:
    """Spalten, Constraints und Indizes von mail_history (ohne Schemanamen)."""
    with engine.connect() as connection:
        columns = connection.execute(
            text(
                "SELECT column_name, data_type, character_maximum_length, is_nullable,"
                " column_default, is_identity FROM information_schema.columns"
                " WHERE table_schema = :s AND table_name = 'mail_history' ORDER BY column_name"
            ),
            {"s": schema_name},
        ).all()
        constraints = connection.execute(
            text(
                "SELECT conname, pg_get_constraintdef(c.oid) FROM pg_constraint c"
                " JOIN pg_namespace n ON n.oid = c.connamespace"
                " WHERE n.nspname = :s AND conrelid = (:s || '.mail_history')::regclass"
                " AND contype <> 'n' ORDER BY conname"
            ),
            {"s": schema_name},
        ).all()
        indexes = connection.execute(
            text(
                "SELECT indexname, replace(indexdef, :s || '.', '') FROM pg_indexes"
                " WHERE schemaname = :s AND tablename = 'mail_history' ORDER BY indexname"
            ),
            {"s": schema_name},
        ).all()
    return {"columns": columns, "constraints": constraints, "indexes": indexes}


def test_parallel_worker_start_creates_table_exactly_once(schema):
    """Nachstellung mehrerer Gunicorn-Worker, die gleichzeitig starten."""
    workers = 8
    barrier = threading.Barrier(workers)
    errors: list[Exception] = []
    engines = [_engine(schema) for _ in range(workers)]

    def start(engine):
        barrier.wait()
        try:
            ensure_mail_history_table(engine)
        except Exception as exc:  # noqa: BLE001 - jeder Fehler ist hier ein Testfehler
            errors.append(exc)

    threads = [threading.Thread(target=start, args=(engine,)) for engine in engines]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    for engine in engines:
        engine.dispose()
    assert errors == []
    assert _describe(_engine(schema), schema)["columns"]


def test_sql_init_file_and_app_startup_create_identical_schema(schema):
    other = f"{schema}_sql"
    admin = create_engine(URL)
    with admin.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{other}"')
    try:
        _run_sql_file(_engine(other), "db/init/002_create_mail_history.sql")
        ensure_mail_history_table(_engine(other))  # bestehende Tabelle: darf nichts aendern
        ensure_mail_history_table(_engine(schema))
        assert _describe(_engine(other), other) == _describe(_engine(schema), schema)
    finally:
        with admin.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{other}" CASCADE')
        admin.dispose()


def test_existing_team_database_gets_only_the_new_table_and_keeps_history(schema):
    engine = _engine(schema)
    _run_sql_file(engine, "db/init/001_create_centers.sql")  # Stand eines bestehenden Volumes
    with engine.connect() as connection:
        before = connection.execute(
            text("SELECT count(*) FROM information_schema.columns WHERE table_schema = :s"), {"s": schema}
        ).scalar_one()

    ensure_mail_history_table(engine)
    with engine.begin() as connection:
        connection.execute(
            MailHistory.__table__.insert().values(
                handoff_id="a" * 32, campaign_id="c" * 32, batch_number=1, batch_count=1,
                subject="Persistenz", body="Text", recipients=["info@example.org"],
                recipient_count=1, bundeslaender=["SN"],
            )
        )
        after = connection.execute(
            text("SELECT count(*) FROM information_schema.columns WHERE table_schema = :s"
                 " AND table_name <> 'mail_history'"),
            {"s": schema},
        ).scalar_one()
    assert after == before  # centers/services/center_services unveraendert
    engine.dispose()

    # "Neustart" der App: neue Verbindung, Daten sind noch da.
    restarted = _engine(schema)
    with restarted.connect() as connection:
        row = connection.execute(
            text("SELECT subject, recipients, status, created_at FROM mail_history")
        ).one()
    assert row.subject == "Persistenz"
    assert row.recipients == ["info@example.org"]
    assert row.status == "handoff_attempted"
    assert row.created_at.tzinfo is not None
    restarted.dispose()


@pytest.mark.parametrize(
    "override",
    [
        {"recipient_count": 21},
        {"recipient_count": 0},
        {"status": "sent"},
        {"batch_number": 3, "batch_count": 2},
    ],
)
def test_database_rejects_rule_violations(schema, override):
    engine = _engine(schema)
    ensure_mail_history_table(engine)
    values = dict(
        handoff_id=uuid.uuid4().hex, campaign_id="c" * 32, batch_number=1, batch_count=1,
        subject="x", body="", recipients=["a@example.org"], recipient_count=1, bundeslaender=[],
    )
    values.update(override)
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(MailHistory.__table__.insert().values(**values))
    engine.dispose()
