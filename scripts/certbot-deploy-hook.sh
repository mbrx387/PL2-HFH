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
# certbot setzt RENEWED_LINEAGE auf z.B. /etc/letsencrypt/live/projekthfh.tech
LINEAGE="${RENEWED_LINEAGE:?nur als certbot --deploy-hook aufrufen (RENEWED_LINEAGE fehlt)}"
CERT_DIR="$APP_DIR/nginx/certs"

install -m 644 "$LINEAGE/fullchain.pem" "$CERT_DIR/fullchain.pem"
install -m 600 "$LINEAGE/privkey.pem"   "$CERT_DIR/privkey.pem"

cd "$APP_DIR"
docker compose exec -T nginx nginx -t
docker compose exec -T nginx nginx -s reload

echo "pl2-hfh: neues Zertifikat aus $LINEAGE installiert, nginx neu geladen."
