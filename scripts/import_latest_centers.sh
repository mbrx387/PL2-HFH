#!/usr/bin/env bash
# Issue #85: Importiert die neueste per scp vom GetDataFromAPI-Workflow abgelegte
# CSV in die App-Datenbank. Laeuft auf dem Server per Cron (scripts/setup_import_cron.sh)
# oder manuell:  ./scripts/import_latest_centers.sh
#
# Pruefung gegen die DB (Sperrvermerk manuell_gepflegt: Eintraege werden weder
# ueberschrieben noch dupliziert) und Import passieren in db/import_centers.sql
# in EINER Transaktion mit ON_ERROR_STOP. NOTICE-Meldungen (z. B. Anzahl der
# uebersprungenen gesperrten Eintraege) landen in diesem Log.
set -Eeuo pipefail

PROJECT_DIR="${PROJECT_DIR:-/opt/pl2-hfh}"
cd "$PROJECT_DIR"

LOG_DIR="${LOG_DIR:-/var/log/pl2-hfh}"
LOG_FILE="$LOG_DIR/import-centers.log"
LOCK_FILE="${LOCK_FILE:-/var/lock/pl2-hfh-import.lock}"
mkdir -p "$LOG_DIR"
exec >>"$LOG_FILE" 2>&1

echo "=== $(date -u '+%Y-%m-%d %H:%M:%S') UTC import_latest_centers.sh ==="

# Gegen Doppellaeufe (Cron + manueller Lauf gleichzeitig).
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "Laeuft bereits - abgebrochen."
  exit 0
fi

CSV="db/temp/pflegestellen.csv"
MARKER="db/temp/.last_imported"

if [ ! -s "$CSV" ]; then
  echo "Keine CSV unter $CSV - nichts zu tun."
  exit 0
fi

sha="$(sha256sum "$CSV" | cut -d' ' -f1)"
if [ -f "$MARKER" ] && [ "$(cat "$MARKER")" = "$sha" ]; then
  echo "CSV $sha wurde bereits importiert - nichts zu tun."
  exit 0
fi

if ! docker compose exec -T app-db pg_isready -U pl2 -d pflegedb -q; then
  echo "FEHLER: app-db ist nicht bereit - Import abgebrochen, Marker nicht gesetzt (Retry beim naechsten Lauf)."
  exit 1
fi

# Migration idempotent mitlaufen lassen (Sperrvermerk-Spalten), falls die App
# sie beim Start noch nicht angelegt hat. db/init ist read-only im Container
# unter /docker-entrypoint-initdb.d eingebunden.
docker compose exec -T app-db psql -v ON_ERROR_STOP=1 -U pl2 -d pflegedb \
  -f /docker-entrypoint-initdb.d/003_manual_maintenance.sql

docker compose cp "$CSV" app-db:/tmp/pflegestellen.csv
docker compose exec -T app-db psql -v ON_ERROR_STOP=1 -U pl2 -d pflegedb \
  < db/import_centers.sql

# Marker ERST nach erfolgreichem Import schreiben: bei einem Fehler bleibt der
# alte Marker stehen und der naechste Lauf retried automatisch.
echo "$sha" > "$MARKER"
echo "Import erfolgreich: $sha"
