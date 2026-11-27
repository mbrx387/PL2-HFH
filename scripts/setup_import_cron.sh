#!/usr/bin/env bash
# Issue #85: installiert den Cron-Eintrag fuer scripts/import_latest_centers.sh
# auf dem Server (als root ausfuehren). Der Server-Cron importiert die jeweils
# neueste CSV, die der GetDataFromAPI-Workflow per scp nach /opt/pl2-hfh/db/temp
# gelegt hat.
#
# Timing: Der GitHub-Actions-Lauf startet Samstag 02:00 UTC und hat ein Timeout
# von 180 Minuten -> der Import-Cron laeuft Samstag 06:00 UTC. Dank Marker
# (sha256 der CSV) ist der Lauf idempotent.
set -Eeuo pipefail

PROJECT_DIR="${PROJECT_DIR:-/opt/pl2-hfh}"
CRON_FILE="/etc/cron.d/pl2-hfh-import"
CRON_LINE="0 6 * * 6 root ${PROJECT_DIR}/scripts/import_latest_centers.sh"

echo "Server-Zeitzone: $(date +%Z) ($(date))"
echo "Hinweis: Die Cron-Zeile ist auf UTC ausgelegt (wie der Actions-Cron)."
echo "         Falls der Server eine andere Zeitzone nutzt, die Stunde in der Cron-Zeile anpassen."

if [ -f "$CRON_FILE" ] && grep -qF "import_latest_centers.sh" "$CRON_FILE"; then
  echo "Cron-Eintrag existiert bereits in $CRON_FILE:"
  cat "$CRON_FILE"
  exit 0
fi

printf '%s\n' "$CRON_LINE" > "$CRON_FILE"
chmod 644 "$CRON_FILE"
echo "Cron installiert ($CRON_FILE):"
cat "$CRON_FILE"
