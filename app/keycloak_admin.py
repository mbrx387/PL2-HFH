#Keycloak-Admin-REST-Client (nur Server-zu-Server).
#Kein master-Realm, kein realm-admin und keine Admin-Zugangsdaten im Browser.

import logging
from urllib.parse import quote
import httpx
from fastapi import HTTPException
from app.config import get_settings, is_placeholder

logger = logging.getLogger(__name__)
GROUPS = frozenset({"Lesend", "Redaktion", "Admins"})

class KeycloakAdmin:
    def __init__(self):
        self.settings = get_settings()
        self.base = (self.settings.oidc_issuer_internal or self.settings.oidc_issuer or "").rstrip("/")
        if not self.base or is_placeholder(self.settings.keycloak_admin_client_secret):
            raise HTTPException(503, "Keycloak-Admin-Service-Account ist nicht konfiguriert")

    async def __aenter__(self):
        self.http = httpx.AsyncClient(timeout=12.0, follow_redirects=False)
        try:
            response = await self.http.post(
                f"{self.base}/protocol/openid-connect/token",
                data={"grant_type": "client_credentials", "client_id": self.settings.keycloak_admin_client_id,
                      "client_secret": self.settings.keycloak_admin_client_secret},
            )
            response.raise_for_status()
            self.http.headers["Authorization"] = f"Bearer {response.json()['access_token']}"
            return self
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            await self.http.aclose()
            logger.error("Keycloak-Service-Account nicht verfuegbar: %s", type(exc).__name__)
            raise HTTPException(503, "Keycloak-Verwaltung momentan nicht verfuegbar") from exc

    async def __aexit__(self, *_):
        await self.http.aclose()

    async def request(self, method, path, **kwargs):
        # base ist die Realm-URL, nicht die Admin-URL.
        # Der interne Keycloak-Host muss aus vertrauenswuerdiger Konfiguration kommen.
        origin, _, realm = self.base.partition('/realms/')
        if realm != 'hfh-pflege':
            raise HTTPException(503, "OIDC-Issuer-Konfiguration ungueltig")
        url = f"{origin}/admin/realms/{quote(realm, safe='')}/{path.lstrip('/')}"
        try:
            r = await self.http.request(method, url, **kwargs)
        except httpx.HTTPError as exc:
            logger.warning("Keycloak-Verbindungsfehler: %s", type(exc).__name__)
            raise HTTPException(503, "Keycloak nicht erreichbar") from exc
        if r.status_code == 404:
            raise HTTPException(404, "Keycloak-Objekt nicht gefunden")
        if r.status_code == 409:
            raise HTTPException(409, "Benutzername oder E-Mail bereits vergeben")
        if r.status_code in (401, 403):
            raise HTTPException(503, "Service-Account-Berechtigungen fehlen")
        if r.status_code >= 400:
            logger.warning("Keycloak-Admin-Fehler %s auf %s", r.status_code, path.split('/')[0])
            raise HTTPException(502, "Keycloak hat die Verwaltungsaktion abgelehnt")
        if r.status_code == 204 or not r.content:
            return None
        try:
            return r.json()
        except ValueError:
            return None

    async def groups(self):
        data = await self.request('GET', 'groups', params={'max': 1000, 'briefRepresentation': 'true'})
        by_name = {g['name']: g['id'] for g in data if g.get('name') in GROUPS}
        if set(by_name) != GROUPS:
            raise HTTPException(503, "Die drei Keycloak-App-Gruppen sind nicht vollstaendig eingerichtet")
        return by_name

    async def user_groups(self, uid):
        return await self.request('GET', f'users/{quote(uid, safe="")}/groups', params={'max': 1000})

    async def set_group(self, uid, group):
        if group not in GROUPS:
            raise HTTPException(422, "Ungueltige Zugriffsgruppe")
        ids = await self.groups()
        existing = await self.user_groups(uid)
        # Erst neue Gruppe zuweisen, dann alte entfernen; alle App-Gruppen exklusiv.
        await self.request('PUT', f'users/{quote(uid, safe="")}/groups/{quote(ids[group], safe="")}')
        for g in existing:
            if g.get('name') in GROUPS and g['id'] != ids[group]:
                await self.request('DELETE', f'users/{quote(uid, safe="")}/groups/{quote(g["id"], safe="")}')
