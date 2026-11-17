#!/usr/bin/env bash
# certbot "deploy hook": laeuft NUR nach einer erfolgreichen Ausstellung oder
# Verlaengerung (nicht bei jedem "certbot renew"-Lauf).
#
# Kopiert das neue Zertifikat in den Ordner, den der nginx-Container liest
# (nginx/certs/), prueft die nginx-Konfiguration und laedt nginx ohne
# Unterbrechung neu. Ohne Reload wuerde nginx weiter das alte Zertifikat
# ausliefern, bis der Container neu startet.
#
# Einrichtung auf dem Server (einmalig, als root):
#   install -m 755 /opt/pl2-hfh/scripts/certbot-deploy-hook.sh \
#     /etc/letsencrypt/renewal-hooks/deploy/pl2-hfh-nginx.sh
# Ausfuehrlich: nginx/README.md, Abschnitt "certbot".
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/pl2-hfh}"
# Nur dieses certbot-Zertifikat (--cert-name) gehoert zu nginx. Hooks in
# /etc/letsencrypt/renewal-hooks/ laufen fuer JEDES Zertifikat auf dem Server -
# ohne diese Pruefung wuerde z.B. ein Zertifikat ohne www.-Namen das richtige
# ueberschreiben.
#
# Derselbe Hook laeuft auf INT und PROD: Ohne gesetztes CERT_NAME gilt der
# Hostname dieses Servers aus $APP_DIR/.env (PUBLIC_HOST, vom Deploy aus
# APP_PUBLIC_URL geschrieben), sonst wie bisher projekthfh.tech.
# Voraussetzung: certbot --cert-name == Hostname (so in nginx/README.md).
if [ -z "${CERT_NAME:-}" ] && [ -f "$APP_DIR/.env" ]; then
  CERT_NAME="$(grep -E '^PUBLIC_HOST=' "$APP_DIR/.env" | tail -n1 | cut -d= -f2- || true)"
fi
CERT_NAME="${CERT_NAME:-projekthfh.tech}"
# certbot setzt RENEWED_LINEAGE auf z.B. /etc/letsencrypt/live/projekthfh.tech
LINEAGE="${RENEWED_LINEAGE:?nur als certbot --deploy-hook aufrufen (RENEWED_LINEAGE fehlt)}"
CERT_DIR="$APP_DIR/nginx/certs"

if [ "$(basename "$LINEAGE")" != "$CERT_NAME" ]; then
  echo "pl2-hfh: $LINEAGE ist nicht '$CERT_NAME' - nichts zu tun."
  exit 0
fi

install -m 644 "$LINEAGE/fullchain.pem" "$CERT_DIR/fullchain.pem"
install -m 600 "$LINEAGE/privkey.pem"   "$CERT_DIR/privkey.pem"

cd "$APP_DIR"
docker compose exec -T nginx nginx -t
docker compose exec -T nginx nginx -s reload

echo "pl2-hfh: neues Zertifikat aus $LINEAGE installiert, nginx neu geladen."
