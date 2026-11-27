"""Issue #85: Spalten fuer den Sperrvermerk manuell gepflegter Einrichtungen.

Wie AP5 (app/mail_models.py, ensure_mail_history_table): db/init/003_manual_maintenance.sql
deckt nur frische Datenbank-Volumes ab; eine BESTEHENDE Datenbank bekommt die
Spalten beim App-Start. Die transaktionale Advisory-Lock-Sperre laesst parallel
startende Gunicorn-Worker nacheinander pruefen (sonst stuerzt einer mit
"column already exists" ab). Bei SQLite (Tests) entfaellt der Lock.
"""

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

# Eigene Lock-ID, kollidiert nicht mit _CREATE_TABLE_LOCK_ID aus mail_models.
_ENSURE_COLUMNS_LOCK_ID = 5_030_001

# Muss zu db/init/003_manual_maintenance.sql passen.
_MANUAL_MAINTENANCE_COLUMNS = {
    "manuell_gepflegt": "boolean NOT NULL DEFAULT false",
    "manuell_geaendert_von": "varchar(255)",
    "manuell_geaendert_am": "timestamptz",
}

# IDs ab diesem Wert gehoeren manuell angelegten Einrichtungen (Issue #85).
MANUAL_ID_START = 1_000_000


def ensure_manual_maintenance_columns(engine: Engine) -> None:
    """Legt die Sperrvermerk-Spalten an, falls sie fehlen, und sperrt Altlasten.

    Idempotent: bei frischen Volumes (db/init/003) und nach dem ersten Start
    aendert der Aufruf nichts mehr.
    """
    with engine.begin() as connection:
        if connection.dialect.name == "postgresql":
            connection.execute(
                text("SELECT pg_advisory_xact_lock(:lock_id)"),
                {"lock_id": _ENSURE_COLUMNS_LOCK_ID},
            )
        existing = {column["name"] for column in inspect(connection).get_columns("centers")}
        for name, ddl in _MANUAL_MAINTENANCE_COLUMNS.items():
            if name not in existing:
                # Kein IF NOT EXISTS noetig (wir pruefen selbst), damit es auch
                # auf SQLite (Tests) funktioniert.
                connection.execute(text(f"ALTER TABLE centers ADD COLUMN {name} {ddl}"))
        # Altlasten: vorhandene manuelle Einrichtungen (id >= 1.000.000) sperren.
        connection.execute(
            text(
                "UPDATE centers SET manuell_gepflegt = true"
                " WHERE id >= :manual_start AND NOT manuell_gepflegt"
            ),
            {"manual_start": MANUAL_ID_START},
        )
        existing = {column["name"] for column in inspect(connection).get_columns("centers")}

    missing = sorted(set(_MANUAL_MAINTENANCE_COLUMNS) - existing)
    if missing:
        # Fail-fast wie die Pruefung der Pflicht-Tabellen in main.py: ein
        # veraltetes Schema wuerde sonst erst beim Speichern scheitern.
        raise RuntimeError(
            "Tabelle centers hat ein veraltetes Schema; fehlende Spalten: "
            + ", ".join(missing)
            + ". Siehe db/init/003_manual_maintenance.sql."
        )
