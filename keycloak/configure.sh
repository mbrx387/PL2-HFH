#!/usr/bin/env bash
# Wendet die Sicherheits- und Rollen-Einstellungen auf einen BESTEHENDEN
# Keycloak-Realm an.
#
# Warum es dieses Skript gibt: keycloak/realm-export.json wird nur beim
# allerersten Start importiert. Existiert der Realm schon (Produktivserver),
# ueberspringt Keycloak die Datei. Dieses Skript setzt dieselben Werte per
# kcadm.sh und kann beliebig oft laufen (idempotent).
#
# Aufruf auf dem Server, im Projektordner (/opt/pl2-hfh):
#   ./keycloak/configure.sh                  # Einstellungen, Rollen, Gruppen
#   ./keycloak/configure.sh --delete-demo    # zusaetzlich Demo-Konto loeschen
#   ./keycloak/configure.sh --enforce-pkce   # zusaetzlich PKCE erzwingen
#
# --enforce-pkce ERST setzen, wenn die App-Version mit PKCE deployt ist
# (app/auth.py: code_challenge_method=S256). Sonst schlaegt jeder Login fehl.
#
# Das Admin-Passwort wird interaktiv abgefragt und nirgends gespeichert.
set -euo pipefail

REALM="${KC_REALM:-hfh-pflege}"
CLIENT_ID="${KC_CLIENT_ID:-pflege-finder}"
ADMIN_USER="${KC_ADMIN_USER:-admin}"
SERVER="${KC_SERVER:-http://localhost:8080/idp}"
KCADM="/opt/keycloak/bin/kcadm.sh"

DELETE_DEMO=false
ENFORCE_PKCE=false
SKIP_LOGIN=false
for arg in "$@"; do
  case "$arg" in
    --delete-demo) DELETE_DEMO=true ;;
    --enforce-pkce) ENFORCE_PKCE=true ;;
    --skip-login) SKIP_LOGIN=true ;;
    -h|--help) sed -n '2,19p' "$0"; exit 0 ;;
    *) echo "Unbekannte Option: $arg" >&2; exit 2 ;;
  esac
done

kc() { docker compose exec -T keycloak "$KCADM" "$@"; }
# Liefert die erste ID einer Abfrage oder nichts.
first_id() { kc get "$@" --fields id --format csv --noquotes 2>/dev/null | head -n1 | tr -d '\r'; }

if [ "$SKIP_LOGIN" = false ]; then
  echo "== Anmeldung als '$ADMIN_USER' (Passwort wird abgefragt)"
  docker compose exec keycloak "$KCADM" config credentials \
    --server "$SERVER" --realm master --user "$ADMIN_USER"
fi

echo "== Realm $REALM: Login-Schutz, Passwoerter, Sprache, Sitzungen"
kc update "realms/$REALM" \
  -s bruteForceProtected=true \
  -s permanentLockout=false \
  -s failureFactor=5 \
  -s waitIncrementSeconds=60 \
  -s maxFailureWaitSeconds=900 \
  -s maxDeltaTimeSeconds=43200 \
  -s 'passwordPolicy=length(12) and notUsername and notEmail and passwordHistory(3)' \
  -s resetPasswordAllowed=false \
  -s rememberMe=false \
  -s registrationAllowed=false \
  -s internationalizationEnabled=true \
  -s 'supportedLocales=["de","en"]' \
  -s defaultLocale=de \
  -s loginTheme=hfh \
  -s ssoSessionIdleTimeout=1800 \
  -s ssoSessionMaxLifespan=28800 \
  -s accessTokenLifespan=300

echo "== Realm $REALM: Audit-Protokoll (30 Tage)"
kc update events/config -r "$REALM" \
  -s eventsEnabled=true \
  -s eventsExpiration=2592000 \
  -s adminEventsEnabled=true \
  -s adminEventsDetailsEnabled=false

echo "== Realm $REALM: Einmalcode (OTP) fuer neue Konten verpflichtend"
kc update authentication/required-actions/CONFIGURE_TOTP -r "$REALM" \
  -s enabled=true -s defaultAction=true

CID="$(first_id clients -r "$REALM" -q "clientId=$CLIENT_ID")"
if [ -z "$CID" ]; then
  echo "Client '$CLIENT_ID' im Realm '$REALM' nicht gefunden." >&2
  exit 1
fi

echo "== Client $CLIENT_ID: Rollen reader/editor/admin"
for role in reader editor admin; do
  if ! kc get "clients/$CID/roles/$role" -r "$REALM" >/dev/null 2>&1; then
    kc create "clients/$CID/roles" -r "$REALM" -s "name=$role"
  fi
done

echo "== Client $CLIENT_ID: Rollen-Claim 'roles' (Mapper application-roles)"
if ! kc get "clients/$CID/protocol-mappers/models" -r "$REALM" --fields name --format csv --noquotes \
    | tr -d '\r' | grep -qx "application-roles"; then
  kc create "clients/$CID/protocol-mappers/models" -r "$REALM" -f - <<JSON
{
  "name": "application-roles",
  "protocol": "openid-connect",
  "protocolMapper": "oidc-usermodel-client-role-mapper",
  "config": {
    "usermodel.clientRoleMapping.clientId": "$CLIENT_ID",
    "multivalued": "true",
    "claim.name": "roles",
    "jsonType.label": "String",
    "id.token.claim": "true",
    "access.token.claim": "true",
    "userinfo.token.claim": "true"
  }
}
JSON
fi

echo "== Client $CLIENT_ID: nur eigene Rollen im Token (Full scope aus)"
kc update "clients/$CID" -r "$REALM" -s fullScopeAllowed=false

echo "== Gruppen Lesend/Redaktion/Admins mit Rollen verknuepfen"
for pair in "Lesend:reader" "Redaktion:editor" "Admins:admin"; do
  group="${pair%%:*}"
  role="${pair##*:}"
  if [ -z "$(first_id groups -r "$REALM" -q "search=$group" -q exact=true)" ]; then
    kc create groups -r "$REALM" -s "name=$group"
  fi
  kc add-roles -r "$REALM" --gname "$group" --cclientid "$CLIENT_ID" --rolename "$role"
done

if [ "$DELETE_DEMO" = true ]; then
  echo "== Demo-Konto loeschen"
  DEMO_ID="$(first_id users -r "$REALM" -q username=demo -q exact=true)"
  if [ -n "$DEMO_ID" ]; then
    kc delete "users/$DEMO_ID" -r "$REALM"
    echo "Demo-Konto geloescht."
  else
    echo "Kein Demo-Konto vorhanden."
  fi
fi

if [ "$ENFORCE_PKCE" = true ]; then
  echo "== Client $CLIENT_ID: PKCE (S256) erzwingen"
  kc update "clients/$CID" -r "$REALM" -s 'attributes."pkce.code.challenge.method"=S256'
fi

echo "== Realm master: Login-Schutz fuer die Admin-Konsole"
kc update realms/master \
  -s bruteForceProtected=true \
  -s failureFactor=5 \
  -s waitIncrementSeconds=60 \
  -s maxFailureWaitSeconds=900

echo
echo "== Ergebnis (Realm $REALM)"
kc get "realms/$REALM" --fields \
  bruteForceProtected,failureFactor,passwordPolicy,resetPasswordAllowed,rememberMe,defaultLocale,ssoSessionIdleTimeout,ssoSessionMaxLifespan,accessTokenLifespan,eventsEnabled,adminEventsEnabled
echo
echo "Fertig. Bestehende Konten haben noch keine Rolle: jede Person unter"
echo "Users -> Groups einer der Gruppen Lesend, Redaktion oder Admins zuordnen."
