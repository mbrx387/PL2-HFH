#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
PROJECT_DIR=$(cd -- "$SCRIPT_DIR/.." && pwd)
OUTPUT="$PROJECT_DIR/nginx/htpasswd.monitoring"

read -r -p "Monitoring-Benutzername [monitoring]: " username
username=${username:-monitoring}

read -r -s -p "Passwort für $username: " password
printf '\n'
read -r -s -p "Passwort bestätigen: " password_confirm
printf '\n'

if [[ -z "$password" ]] || [[ "$password" != "$password_confirm" ]]; then
  echo "Passwort leer oder nicht bestätigt" >&2
  exit 1
fi

if command -v htpasswd >/dev/null 2>&1; then
  htpasswd -bBc "$OUTPUT" "$username" "$password" >/dev/null
else
  if ! command -v openssl >/dev/null 2>&1; then
    echo "Weder htpasswd noch openssl ist verfügbar" >&2
    exit 1
  fi
  salt=$(openssl rand -hex 4)
  hash=$(openssl passwd -apr1 -salt "$salt" "$password")
  printf '%s:%s\n' "$username" "$hash" > "$OUTPUT"
fi

# 644 statt 600: nginx mountet die Datei als Datei-Bind-Mount (Host-Rechte
# gelten im Container). Der nginx-Worker laeuft als User "nginx" (uid 101),
# nicht als root - mit 600 root:root kann er die Datei nicht lesen und nginx
# antwortet "open() ... failed (13: Permission denied)" -> HTTP 500.
chmod 644 "$OUTPUT"
unset password password_confirm
echo "Monitoring-Zugang gespeichert: $OUTPUT"
