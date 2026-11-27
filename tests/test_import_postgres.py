"""Issue #85: Import-Schutz gegen ein ECHTES PostgreSQL (optional, in CI uebersprungen).

Aktivieren nur mit einer WEGWERF-Testdatenbank, niemals mit Produktivdaten:

    PL2_TEST_POSTGRES_URL=postgresql://pl2:PASSWORT@localhost:5432/pflegedb_test \
        pytest -q tests/test_import_postgres.py

Schutz: Der Datenbankname muss "test" enthalten. Jeder Test arbeitet in einem
eigenen, zufaellig benannten Schema, das am Ende wieder geloescht wird.

Getestet wird das echte db/import_centers.sql (wie produktiv ausgefuehrt): die
\\copy-Zeile wird durch COPY ... FROM STDIN ersetzt und die CSV per psycopg
gestreamt (gleiches Vorgehen wie e2e/db_seed.py).
"""

import csv
import io
import os
import re
import uuid
from pathlib import Path

import pytest

psycopg = pytest.importorskip("psycopg")
from psycopg.rows import dict_row  # noqa: E402  (nach importorskip)

URL = os.environ.get("PL2_TEST_POSTGRES_URL")
ROOT = Path(__file__).parent.parent

pytestmark = pytest.mark.skipif(not URL, reason="PL2_TEST_POSTGRES_URL nicht gesetzt")

FIELDS = [
    "unsere_id", "zqp_id", "name", "adresse", "plz", "ort", "bundesland",
    "email", "telefon", "website", "latitude", "longitude",
    "pflegestuetzpunkt", "pflegeberatung", "wohnberatung", "demenzberatung",
    "angehoerigenberatung", "betreuungsberatung", "leistungen", "updated_at",
]

_COPY_LINE = re.compile(r"^\\copy\s+(?P<table>\S+)\s+FROM\s+'[^']*'\s+(?P<options>WITH\s*\(.*\))\s*$", re.M)


def make_csv(rows: list[dict]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=FIELDS, delimiter=";", lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({field: row.get(field, "") for field in FIELDS})
    return buffer.getvalue()


def row(unsere_id, zqp_id="", name="Teststelle", adresse="Musterstr. 1", plz="01067",
        ort="Dresden", bundesland="SN", leistungen="", leistung_flags="0;0;0;0;0;0",
        latitude="51.05", longitude="13.7"):
    flag_fields = ["pflegestuetzpunkt", "pflegeberatung", "wohnberatung",
                   "demenzberatung", "angehoerigenberatung", "betreuungsberatung"]
    flags = dict(zip(flag_fields, leistung_flags.split(";"), strict=True))
    return {
        "unsere_id": unsere_id, "zqp_id": zqp_id, "name": name, "adresse": adresse,
        "plz": plz, "ort": ort, "bundesland": bundesland, "latitude": latitude,
        "longitude": longitude, "leistungen": leistungen, "updated_at": "2026-01-01 10:00:00",
        **flags,
    }


# psycopg3 hat kein conn.notices (das war psycopg2) — NOTICEs laufen ueber einen
# Notice-Handler; hier pro Verbindung sammeln.
_NOTICES: dict[int, list[str]] = {}


def notices_of(conn) -> list[str]:
    return _NOTICES[id(conn)]


@pytest.fixture
def db():
    assert URL and "test" in URL.rsplit("/", 1)[-1], (
        "Sicherheitsstopp: PL2_TEST_POSTGRES_URL muss auf eine *test*-Datenbank zeigen."
    )
    schema = f"import_test_{uuid.uuid4().hex[:10]}"
    with psycopg.connect(URL, autocommit=True) as admin:
        admin.execute(f'CREATE SCHEMA "{schema}"')
    conn = psycopg.connect(URL, autocommit=True, row_factory=dict_row,
                           options=f"-c search_path={schema}")
    notices: list[str] = []
    _NOTICES[id(conn)] = notices
    conn.add_notice_handler(lambda n: notices.append(n.message_primary or ""))
    try:
        for init_file in ("db/init/001_create_centers.sql", "db/init/003_manual_maintenance.sql"):
            conn.execute((ROOT / init_file).read_text(encoding="utf-8"))
        yield conn
    finally:
        conn.close()
        _NOTICES.pop(id(conn), None)
        with psycopg.connect(URL, autocommit=True) as admin:
            admin.execute(f'DROP SCHEMA "{schema}" CASCADE')


def run_import(conn, csv_text: str) -> None:
    """Fuehrt das echte db/import_centers.sql aus (\\copy -> COPY FROM STDIN)."""
    script = (ROOT / "db" / "import_centers.sql").read_text(encoding="utf-8")
    match = _COPY_LINE.search(script)
    assert match, "Keine \\copy-Zeile in db/import_centers.sql gefunden"
    copy_sql = f"COPY {match['table']} FROM STDIN {match['options']}"
    with conn.cursor() as cur:
        cur.execute(script[: match.start()])
        with cur.copy(copy_sql) as copy:
            copy.write(csv_text.encode("utf-8"))
        cur.execute(script[match.end():])


def center(conn, center_id: int) -> dict | None:
    return conn.execute("SELECT * FROM centers WHERE id = %s", (center_id,)).fetchone()


def service_names(conn, center_id: int) -> set[str]:
    return {
        r["name"]
        for r in conn.execute(
            "SELECT s.name FROM center_services cs JOIN services s ON s.id = cs.service_id"
            " WHERE cs.center_id = %s",
            (center_id,),
        ).fetchall()
    }


def center_count(conn) -> int:
    return conn.execute("SELECT count(*) AS n FROM centers").fetchone()["n"]


def test_import_upsert_insert_then_update(db):
    run_import(db, make_csv([row(10, zqp_id="ZQP1", name="Alt", leistungen="Pflegeberatung")]))
    assert center(db, 10)["name"] == "Alt"
    assert service_names(db, 10) == {"Pflegeberatung"}

    run_import(db, make_csv([row(10, zqp_id="ZQP1", name="Neu", leistungen="Wohnberatung")]))
    assert center(db, 10)["name"] == "Neu"
    assert service_names(db, 10) == {"Wohnberatung"}
    assert center_count(db) == 1


def test_locked_entry_matched_by_id_is_untouched(db):
    run_import(db, make_csv([row(10, zqp_id="ZQP1", name="Alt", leistungen="Pflegeberatung")]))
    db.execute(
        "UPDATE centers SET manuell_gepflegt = true, name = 'Manuell',"
        " manuell_geaendert_von = 'mmustermann', manuell_geaendert_am = now() WHERE id = 10"
    )
    notices_of(db).clear()

    run_import(db, make_csv([row(10, zqp_id="ZQP1", name="Ueberschrieben", leistungen="Wohnberatung")]))

    locked = center(db, 10)
    assert locked["name"] == "Manuell"  # Felder unberuehrt
    assert locked["manuell_gepflegt"] is True
    assert locked["manuell_geaendert_von"] == "mmustermann"  # Sperrvermerk nicht zurueckgesetzt
    assert service_names(db, 10) == {"Pflegeberatung"}  # Angebote unberuehrt
    assert any("manuell gesperrt" in notice for notice in notices_of(db))


def test_locked_entry_matched_by_zqp_id_with_other_id_is_skipped(db):
    run_import(db, make_csv([row(10, zqp_id="ZQP1", name="Alt")]))
    db.execute("UPDATE centers SET manuell_gepflegt = true WHERE id = 10")
    notices_of(db).clear()

    # Import-Zeile mit neuer ID, aber derselben zqp_id: darf weder einen zweiten
    # Datensatz anlegen noch die UNIQUE-Constraint auf zqp_id verletzen.
    run_import(db, make_csv([row(55, zqp_id="ZQP1", name="Duplikat")]))

    assert center(db, 55) is None
    assert center_count(db) == 1
    assert center(db, 10)["name"] == "Alt"
    assert any("manuell gesperrt" in notice for notice in notices_of(db))


def test_locked_manual_entry_without_zqp_id_matched_by_local_key_is_skipped(db):
    # Manuell angelegte Einrichtung (id >= 1.000.000, keine zqp_id), durch die
    # Migration automatisch gesperrt.
    db.execute(
        "INSERT INTO centers (id, zqp_id, name, adresse, plz, ort, bundesland, manuell_gepflegt)"
        " VALUES (1000000, NULL, 'Manuell X', 'Musterstr. 1', '01067', 'Dresden', 'SN', true)"
    )
    notices_of(db).clear()

    # Quelle liefert dieselbe reale Einrichtung (LOCAL-Key matcht, zqp_id leer).
    run_import(db, make_csv([row(77, zqp_id="", name="Manuell X", adresse="Musterstr. 1",
                                 plz="01067", ort="Dresden")]))

    assert center(db, 77) is None  # kein Duplikat
    assert center_count(db) == 1
    assert center(db, 1000000)["name"] == "Manuell X"
    assert any("manuell gesperrt" in notice for notice in notices_of(db))


def test_zqp_id_collision_with_unlocked_entry_rewrites_id(db):
    run_import(db, make_csv([row(10, zqp_id="ZQP1", name="Alt")]))

    # Dieselbe zqp_id unter anderer unsere_id: kein Duplikat, kein UNIQUE-Fehler,
    # sondern Update des bestehenden Datensatzes.
    run_import(db, make_csv([row(99, zqp_id="ZQP1", name="Neu")]))

    assert center(db, 99) is None
    assert center_count(db) == 1
    assert center(db, 10)["name"] == "Neu"


def test_guard_aborts_import_on_manual_id_and_rolls_back(db):
    run_import(db, make_csv([row(10, zqp_id="ZQP1", name="Alt")]))

    with pytest.raises(psycopg.Error, match="manueller ID-Bereich"):
        run_import(db, make_csv([row(1000000, zqp_id="ZQP9", name="Boese")]))
    db.rollback()  # abgebrochene Transaktion aufraeumen

    # Rollback: DB-Zustand unveraendert.
    assert center_count(db) == 1
    assert center(db, 10)["name"] == "Alt"
    assert center(db, 1000000) is None
