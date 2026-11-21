"""Setzt die E2E-Datenbank auf einen definierten Ausgangszustand zurueck.

Nutzt bewusst das echte Importskript db/import_centers.sql (dasselbe, das der
ETL-Workflow produktiv ausfuehrt), damit es nur EINE Import-Logik gibt und sie
nebenbei mitgetestet wird. Das Skript liest die CSV per psql-Metabefehl
``\\copy`` von einer Datei im Container; hier wird genau diese Zeile durch ein
serverseitiges ``COPY ... FROM STDIN`` ersetzt und die CSV ueber psycopg
gestreamt. Alles andere (BEGIN, Temp-Tabelle, Upsert, Services, COMMIT) laeuft
unveraendert.

Tests beziehen sich auf den Seed: die Gesamtzahl ueber SEED_COUNT, einzelne
Erwartungen (z. B. "3 Einrichtungen in Bayern", "5 mit E-Mail-Adresse") direkt
auf den Inhalt von e2e/data/centers.csv. Wer die CSV aendert, passt diese mit an.
"""
import csv
import re
from pathlib import Path

import psycopg

E2E_DIR = Path(__file__).resolve().parent
REPO_ROOT = E2E_DIR.parent
IMPORT_SQL = REPO_ROOT / "db" / "import_centers.sql"
SEED_CSV = E2E_DIR / "data" / "centers.csv"


def _count_seed_rows(path: Path) -> int:
    with path.open(encoding="utf-8", newline="") as source:
        return sum(1 for row in csv.DictReader(source, delimiter=";") if row.get("unsere_id"))


# Anzahl Datensaetze im Seed - aus der CSV abgeleitet statt hart kodiert.
SEED_COUNT = _count_seed_rows(SEED_CSV)

_COPY_LINE = re.compile(r"^\\copy\s+(?P<table>\S+)\s+FROM\s+'[^']*'\s+(?P<options>WITH\s*\(.*\))\s*$", re.M)


def _split_import_script() -> tuple[str, str, str]:
    """Liefert (Teil vor \\copy, COPY-FROM-STDIN-Befehl, Teil nach \\copy)."""
    script = IMPORT_SQL.read_text(encoding="utf-8")
    match = _COPY_LINE.search(script)
    if match is None:
        raise RuntimeError(f"Keine \\copy-Zeile in {IMPORT_SQL} gefunden - Importskript geaendert?")
    copy_sql = f"COPY {match['table']} FROM STDIN {match['options']}"
    return script[: match.start()], copy_sql, script[match.end() :]


def reset_database(database_url: str, csv_path: Path) -> None:
    """Leert alle Einrichtungen und importiert den Seed-Datensatz neu.

    ``services`` bleibt erhalten (Standardleistungen aus db/init); fehlende
    Leistungen legt das Importskript selbst an.
    """
    before_copy, copy_sql, after_copy = _split_import_script()
    # autocommit: Das Importskript steuert seine Transaktion selbst
    # (BEGIN ... COMMIT); die Temp-Tabelle lebt bis zum COMMIT.
    with psycopg.connect(database_url, autocommit=True) as conn:
        conn.execute("TRUNCATE center_services, centers")
        with conn.cursor() as cur:
            cur.execute(before_copy)
            with cur.copy(copy_sql) as copy:
                copy.write(csv_path.read_bytes())
            cur.execute(after_copy)
