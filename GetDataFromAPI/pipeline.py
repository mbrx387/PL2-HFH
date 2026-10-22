"""Extract, validate, merge and atomically publish one CSV candidate."""

import csv
import json
import logging
import math
import os
import tempfile
import time
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from GetDataFromAPI.transform import convert_item, duplicate_key

logger = logging.getLogger(__name__)
SERVICE_FIELDS = (
    "pflegestuetzpunkt",
    "pflegeberatung",
    "wohnberatung",
    "demenzberatung",
    "angehoerigenberatung",
    "betreuungsberatung",
)
COLUMNS = (
    "unsere_id",
    "zqp_id",
    "name",
    "adresse",
    "plz",
    "ort",
    "bundesland",
    "email",
    "telefon",
    "website",
    "latitude",
    "longitude",
    *SERVICE_FIELDS,
    "leistungen",
    "updated_at",
)


class ImportFailure(Exception):
    """A failed import must never publish a partial replacement."""


def grid(step=Decimal("0.15")):
    """Integer-indexed coordinates avoid floating point drift at boundaries."""
    if not step.is_finite() or step <= 0:
        raise ImportFailure("Grid step must be positive / Rasterweite muss positiv sein.")
    for lat_index in range(int(Decimal("7.90") / step) + 1):
        for lng_index in range(int(Decimal("9.40") / step) + 1):
            yield float(Decimal("47.20") + lat_index * step), float(Decimal("5.80") + lng_index * step)


def fetch_point(endpoint, latitude, longitude, *, attempts=3, delay=0.3, sleep=time.sleep, open_url=urlopen):
    """Retry timeouts, connection errors, HTTP 429 and 5xx; fail on bad payloads."""
    query = urlencode({"filter": "2,1,3,6,4,5", "lat": latitude, "lng": longitude})
    request = Request(f"{endpoint}?{query}", headers={"User-Agent": "ZQP-Studienprojekt/1.0"})
    for attempt in range(attempts):
        # Throttle every request, including retries and failed requests.
        sleep(delay)
        try:
            with open_url(request, timeout=30) as response:
                payload = json.load(response)
            if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
                raise ImportFailure("Unexpected API schema / Unerwartetes API-Schema.")
            if not all(isinstance(item, dict) for item in payload["data"]):
                raise ImportFailure("Invalid source records / Ungueltige Quelldatensaetze.")
            return payload["data"]
        except HTTPError as error:
            if error.code != 429 and not 500 <= error.code < 600:
                raise ImportFailure(f"API HTTP {error.code}; import stopped / Import abgebrochen.") from None
        except (URLError, TimeoutError, ConnectionError):
            pass
        except (ValueError, UnicodeError):
            raise ImportFailure("Invalid API JSON / Ungueltiges API-JSON.") from None
        if attempt + 1 < attempts:
            logger.warning("Temporary API failure; retry %d/%d / Wiederholung", attempt + 1, attempts - 1)
            sleep(2**attempt)
    raise ImportFailure("API unavailable after retries / API nach Wiederholungen nicht erreichbar.")


def validate_records(records, *, require_name=True):
    ids, keys = set(), set()
    for record in records:
        try:
            identifier = int(record["unsere_id"])
        except (KeyError, ValueError, TypeError):
            raise ImportFailure("Invalid existing ID / Ungueltige bestehende ID.") from None
        key = duplicate_key(record)
        if identifier <= 0 or identifier in ids or key in keys:
            raise ImportFailure("Duplicate ID/key or missing name / Doppelte ID/Schluessel oder Name fehlt.")
        if require_name and not str(record.get("name", "")).strip():
            raise ImportFailure("Source record has no name / Quelldatensatz ohne Namen.")
        for field, bound in (("latitude", 90), ("longitude", 180)):
            value = record.get(field)
            if value not in (None, ""):
                try:
                    number = float(value)
                except (ValueError, TypeError):
                    raise ImportFailure("Invalid coordinate / Ungueltige Koordinate.") from None
                if not math.isfinite(number) or abs(number) > bound:
                    raise ImportFailure("Coordinate out of range / Koordinate ausserhalb des Wertebereichs.")
        ids.add(identifier)
        keys.add(key)


def read_baseline(path):
    # A baseline is required: silently starting over would break stable app IDs.
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=";")
        if set(reader.fieldnames or []) != set(COLUMNS) or len(reader.fieldnames or []) != len(COLUMNS):
            raise ImportFailure("Baseline CSV columns missing / Spalten der Basis-CSV fehlen.")
        records = list(reader)
    if any(set(row) != set(COLUMNS) or any(value is None for value in row.values()) for row in records):
        raise ImportFailure("Malformed CSV row / Fehlerhafte CSV-Zeile.")
    if not records:
        raise ImportFailure("Baseline is empty / Basisdaten sind leer.")
    validate_records(records, require_name=False)
    missing_names = sum(not item.get("name", "").strip() for item in records)
    if missing_names:
        logger.warning("Baseline records without names / Bestandsdaten ohne Namen: %d", missing_names)
    return records


def merge_records(baseline, source):
    """Keep stable IDs and unseen records; source values refresh matched records."""
    records = {duplicate_key(item): dict(item) for item in baseline}
    next_id = max((int(item["unsere_id"]) for item in baseline), default=0) + 1
    timestamp = datetime.now(UTC).isoformat()
    for raw in source:
        converted = convert_item(raw, next_id)
        key = duplicate_key(converted)
        existing = records.get(key)
        converted.pop("zqp_raw", None)
        converted["updated_at"] = timestamp
        converted["leistungen"] = ", ".join(converted["leistungen"])
        validate_records([converted], require_name=existing is None)
        if existing:
            converted["unsere_id"] = int(existing["unsere_id"])
            # Do not erase existing contact/address values if the source omits them.
            for field in (
                "name",
                "adresse",
                "plz",
                "ort",
                "bundesland",
                "email",
                "telefon",
                "website",
                "latitude",
                "longitude",
            ):
                if converted.get(field) in (None, ""):
                    converted[field] = existing.get(field, "")
        else:
            next_id += 1
        records[key] = converted
    result = sorted(records.values(), key=lambda item: int(item["unsere_id"]))
    validate_records(result, require_name=False)
    return result


def write_candidate(path, records):
    """Stage on the same filesystem; replace only after a complete durable write."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8-sig",
            newline="",
            dir=path.parent,
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            writer = csv.DictWriter(handle, fieldnames=COLUMNS, delimiter=";")
            writer.writeheader()
            writer.writerows(records)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def run(endpoint, baseline_path, output_path, *, coordinates=None, fetch=fetch_point):
    try:
        url = urlsplit(endpoint)
    except ValueError:
        raise ImportFailure("Invalid API URL / Ungueltige API-URL.") from None
    if url.scheme != "https" or not url.netloc or url.query or url.fragment:
        raise ImportFailure("Set a valid HTTPS API URL / Gueltige HTTPS-API-URL konfigurieren.")
    if baseline_path.resolve() == output_path.resolve():
        raise ImportFailure("Output must differ from baseline / Ausgabe muss von Basisdatei abweichen.")
    baseline = read_baseline(baseline_path)
    previous_snapshot = output_path.with_name(f"{output_path.stem}_new.json")
    if previous_snapshot.exists():
        try:
            previous = json.loads(previous_snapshot.read_text(encoding="utf-8"))
            if not isinstance(previous, list) or not all(isinstance(row, dict) for row in previous):
                raise ValueError
            validate_records(previous, require_name=False)
        except (ValueError, TypeError, KeyError, AttributeError):
            raise ImportFailure("Invalid previous snapshot / Vorheriger Datenstand ungueltig.") from None
        baseline = previous
    # Collect a complete extraction before loading any candidate; no partial publication.
    source = []
    count = 0
    for latitude, longitude in grid() if coordinates is None else coordinates:
        source.extend(fetch(endpoint, latitude, longitude))
        count += 1
        if count % 100 == 0:
            logger.info("Completed queries / Abgeschlossene Abfragen: %d", count)
    if not source:
        raise ImportFailure("Source returned no records / Quelle lieferte keine Datensaetze.")
    known_keys = {duplicate_key(row) for row in baseline}
    accepted, rejected = [], []
    for raw in source:
        converted = convert_item(raw, 1)
        if not converted["name"] and duplicate_key(converted) not in known_keys:
            rejected.append({"zqp_id": converted["zqp_id"], "reason": "Missing name / Name fehlt"})
        else:
            accepted.append(raw)
    if not accepted:
        raise ImportFailure("No usable source records / Keine verwendbaren Quelldatensaetze.")
    if rejected:
        logger.warning("Records quarantined / Datensaetze zur Pruefung ausgesondert: %d", len(rejected))
    result = merge_records(baseline, accepted)
    from GetDataFromAPI.export import publish_exports

    changes = publish_exports(output_path, baseline, result, rejected=rejected)
    logger.info("Excel/JSON old, new, changes written / geschrieben; changes=%d", changes)
    logger.info("Import complete / Import abgeschlossen: queries=%d records=%d", count, len(result))
    return len(result)
