#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
PROJECT_DIR=${PROJECT_DIR:-"$(cd -- "$SCRIPT_DIR/.." && pwd)"}
BACKUP_DIR=${BACKUP_DIR:-/var/backups/pl2-hfh}
RETENTION_DAYS=${RETENTION_DAYS:-14}
STAMP=$(date -u +%Y%m%dT%H%M%SZ)

if [[ ! "$RETENTION_DAYS" =~ ^[0-9]+$ ]] || (( RETENTION_DAYS < 1)); then
  echo "RETENTION_DAYS muss eine positive Ganzzahl sein" >&2
  exit 1
fi

cd "$PROJECT_DIR"
mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

# Ein laufender Job verhindert einen zweiten gleichzeitigen Lauf.
if command -v flock >/dev/null 2>&1; then
  exec 9>"$BACKUP_DIR/.backup.lock"
  flock -n 9 || { echo "Ein Datenbank-Backup läuft bereits" >&2; exit 1; }
fi

umask 077
CURRENT_TEMP=""
trap '[[ -z "$CURRENT_TEMP" ]] || rm -f -- "$CURRENT_TEMP"' EXIT

backup_database() {
  local name=$1
  local service=$2
  local database=$3
  local user=$4
  local final_file="$BACKUP_DIR/${name}-${STAMP}.dump"
  local temp_file
  temp_file=$(mktemp "$BACKUP_DIR/.${name}-${STAMP}.XXXXXX.tmp")
  CURRENT_TEMP=$temp_file

  echo "Sichere $database über $service ..."
  docker compose exec -T "$service" pg_dump \
    -Fc -Z 9 -U "$user" -d "$database" > "$temp_file"

  if [[ ! -s "$temp_file" ]]; then
    rm -f "$temp_file"
    echo "Backup fehlgeschlagen: $final_file ist leer" >&2
    exit 1
  fi

  # Prüft, ob das Custom-Format lesbar ist und einen gültigen Dump enthält.
  local container_temp="/tmp/backup-${STAMP}-${name}.dump"
  docker compose cp "$temp_file" "$service:$container_temp"
  docker compose exec -T "$service" pg_restore --list "$container_temp" >/dev/null
  docker compose exec -T "$service" rm -f "$container_temp"

  mv -f "$temp_file" "$final_file"
  CURRENT_TEMP=""
  chmod 600 "$final_file"
  echo "OK: $final_file ($(wc -c < "$final_file" | tr -d '[:space:]') Bytes)"
}

# Beide Dienste müssen laufen. Das SSO-Profil muss beim Serverstart aktiviert sein.
docker compose ps --services --status running | grep -Fxq app-db || {
  echo "Dienst app-db läuft nicht" >&2
  exit 1
}
docker compose ps --services --status running | grep -Fxq keycloak-db || {
  echo "Dienst keycloak-db läuft nicht; ggf. docker compose --profile sso up -d keycloak-db" >&2
  exit 1
}

backup_database pflegedb app-db pflegedb pl2
backup_database keycloak keycloak-db keycloak keycloak

find "$BACKUP_DIR" -type f -name 'pflegedb-*.dump' -mtime "+$RETENTION_DAYS" -delete
find "$BACKUP_DIR" -type f -name 'keycloak-*.dump' -mtime "+$RETENTION_DAYS" -delete

find "$BACKUP_DIR" -type f -name '.*.tmp' -delete

echo "Backup abgeschlossen: $STAMP; Aufbewahrung: $RETENTION_DAYS Tage"
