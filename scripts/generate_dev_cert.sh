#!/usr/bin/env bash
# Erzeugt ein selbstsigniertes TLS-Zertifikat für die lokale Entwicklung /
# Demo-Umgebung. NICHT für den Produktivbetrieb geeignet - dort übernimmt
# Let's Encrypt / certbot die Zertifikatsausstellung (siehe README).
set -euo pipefail

CERT_DIR="$(dirname "$0")/../nginx/certs"
mkdir -p "$CERT_DIR"

openssl req -x509 -nodes -days 365 \
  -newkey rsa:2048 \
  -keyout "$CERT_DIR/privkey.pem" \
  -out "$CERT_DIR/fullchain.pem" \
  -subj "/C=DE/O=Hochschule-Projekt/CN=localhost"

echo "Selbstsigniertes Dev-Zertifikat erzeugt in $CERT_DIR"
