"""Befuellt die In-Memory-Datenbank beim Start aus app/data/pflegestellen.csv.

Die CSV ist die versionierte "Quelle der Wahrheit" fuer die Demo-/Startdaten.
Ein spaeterer Import-/Sync-Job (z.B. aus einer amtlichen Quelle) kann diesen
Loader 1:1 ersetzen, ohne dass sich am Rest der Anwendung etwas aendert.
"""
import csv
import logging
from pathlib import Path

from sqlalchemy.orm import Session

from app.models import Center

logger = logging.getLogger(__name__)

BOOL_TRUE = {"1", "true", "True", "ja", "yes"}


def _to_bool(value: str | None) -> bool:
    return (value or "").strip() in BOOL_TRUE


def _to_float(value: str | None) -> float | None:
    if not value or not value.strip():
        return None
    try:
        return float(value)
    except ValueError:
        return None


def load_centers_from_csv(db: Session, csv_path: str) -> int:
    path = Path(csv_path)
    if not path.exists():
        logger.warning("Seed-Datei %s nicht gefunden - Datenbank bleibt leer.", path)
        return 0

    inserted = 0
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            db.add(
                Center(
                    name=(row.get("name") or "").strip(),
                    adresse=(row.get("adresse") or "").strip(),
                    plz=(row.get("plz") or "").strip(),
                    ort=(row.get("ort") or "").strip(),
                    bundesland=(row.get("bundesland") or "").strip(),
                    email=(row.get("email") or "").strip(),
                    telefon=(row.get("telefon") or "").strip(),
                    website=(row.get("website") or "").strip(),
                    latitude=_to_float(row.get("latitude")),
                    longitude=_to_float(row.get("longitude")),
                    pflegestuetzpunkt=_to_bool(row.get("pflegestuetzpunkt")),
                    pflegeberatung=_to_bool(row.get("pflegeberatung")),
                    wohnberatung=_to_bool(row.get("wohnberatung")),
                    demenzberatung=_to_bool(row.get("demenzberatung")),
                    angehoerigenberatung=_to_bool(row.get("angehoerigenberatung")),
                    betreuungsberatung=_to_bool(row.get("betreuungsberatung")),
                    leistungen=(row.get("leistungen") or "").strip(),
                )
            )
            inserted += 1
    db.commit()
    logger.info("Seed abgeschlossen: %d Eintraege aus %s geladen.", inserted, path)
    return inserted
