#geschuetzte Benutzerverwaltung

import hmac
import logging
import re
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.auth import require_permission
from app.config import get_settings
from app.keycloak_admin import GROUPS, KeycloakAdmin

logger = logging.getLogger(__name__)
# niemals Admin-API ohne echte Admin-Sitzung
async def require_admin_session(user: dict =
    Depends(require_permission("manage_users"))):
    if not get_settings().auth_enabled or not user:
        raise HTTPException(403, 'Admin-Anmeldung erforderlich')
        return user

router = APIRouter(prefix='/api/admin', tags=['admin'], dependencies=[Depends(require_admin_session)])
UID_RE = re.compile(r'^[0-9a-fA-F-]{36}$')

class CreateUser(BaseModel):
    username: str = Field(min_length=3, max_length=100, pattern=r'^[a-zA-Z0-9._@-]+$')
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=12, max_length=256)
    group: str

class EnabledUpdate(BaseModel):
    enabled: bool

class GroupUpdate(BaseModel):
    group: str | None


def validate_uid(uid):
    if not UID_RE.fullmatch(uid):
        raise HTTPException(422, 'Ungueltige Benutzer-ID')
    return uid


def check_csrf(request: Request):
    # Ein einmaliges Token ist in der signierten App-Session hinterlegt und
    # muss in einem nicht-simple Request-Header zurueckgesendet werden.
    token = request.session.get('admin_csrf')
    supplied = request.headers.get('x-csrf-token', '')
    if not isinstance(token, str) or not token or not hmac.compare_digest(token, supplied):
        raise HTTPException(403, 'CSRF-Pruefung fehlgeschlagen')
    origin = request.headers.get('origin')
    if origin:
        actual = urlsplit(origin)
        expected = request.url
        if actual.scheme != expected.scheme or actual.netloc != expected.netloc:
            raise HTTPException(403, 'Ungueltiger Origin')


def audit(request, action, uid):
    actor = (request.session.get('user') or {}).get('sub', 'unknown')
    logger.info('issue60_audit actor=%s action=%s target=%s', actor, action, uid)


@router.get('/users')
async def list_users(request: Request):
    async with KeycloakAdmin() as kc:
        users = await kc.request('GET', 'users', params={'max': 100, 'first': 0, 'briefRepresentation': 'true'})
        result = []
        for u in users:
            assigned = await kc.user_groups(u['id'])
            app_groups = [g['name'] for g in assigned if g.get('name') in GROUPS]
            group = app_groups[0] if len(app_groups) == 1 else None
            result.append({'id': u['id'], 'username': u.get('username', ''), 'email': u.get('email', ''),
                           'enabled': u.get('enabled', False), 'group': group,
                           'is_self': u['id'] == (request.session.get('user') or {}).get('sub')})
        return result


@router.post('/users', status_code=201)
async def create_user(payload: CreateUser, request: Request):
    check_csrf(request)
    if payload.group not in GROUPS:
        raise HTTPException(422, 'Ungueltige Zugriffsgruppe')
    if '@' not in payload.email or payload.email.startswith('@') or payload.email.endswith('@'):
        raise HTTPException(422, 'Ungueltige E-Mail-Adresse')
    if payload.username.casefold() in payload.password.casefold() or str(payload.email).casefold() in payload.password.casefold():
        raise HTTPException(422, 'Passwort darf Benutzername und E-Mail nicht enthalten')
    async with KeycloakAdmin() as kc:
        await kc.groups()  # Fail-fast bei falscher Realm-Konfiguration
        await kc.request('POST', 'users', json={'username': payload.username, 'email': str(payload.email),
            'enabled': False, 'emailVerified': False, 'requiredActions': ['UPDATE_PASSWORD', 'CONFIGURE_TOTP'],
            'credentials': [{'type': 'password', 'value': payload.password, 'temporary': True}]})
        matches = await kc.request('GET', 'users', params={'username': payload.username, 'exact': 'true', 'max': 2})
        if len(matches) != 1:
            raise HTTPException(502, 'Benutzer erstellt, Gruppenzuweisung muss manuell geprueft werden')
        uid = matches[0]['id']
        try:
            await kc.set_group(uid, payload.group)
            await kc.request('PUT', f'users/{uid}', json={'enabled': True})
        except HTTPException:
            # Keine stillschweigend nutzbaren Konten ohne zugewiesene Gruppe.
            await kc.request('PUT', f'users/{uid}', json={'enabled': False})
            raise
    audit(request, 'create_user', uid)
    return {'id': uid, 'username': payload.username}


@router.put('/users/{uid}/enabled')
async def update_enabled(uid: str, payload: EnabledUpdate, request: Request):
    check_csrf(request)
    uid = validate_uid(uid)
    if not payload.enabled and uid == (request.session.get('user') or {}).get('sub'):
        raise HTTPException(409, 'Eigenes Konto kann nicht deaktiviert werden')
    async with KeycloakAdmin() as kc:
        if not payload.enabled:
            groups = await kc.user_groups(uid)
            if any(g.get('name') == 'Admins' for g in groups):
                raise HTTPException(409, 'Admin-Konten nur in der Keycloak-Konsole deaktivieren (Schutz vor letztem Admin)')
        await kc.request('PUT', f'users/{uid}', json={'enabled': payload.enabled})
        if not payload.enabled:
            await kc.request('POST', f'users/{uid}/logout')
    audit(request, 'enable_user' if payload.enabled else 'disable_user', uid)
    return {'id': uid, 'enabled': payload.enabled}


@router.put('/users/{uid}/group')
async def update_group(uid: str, payload: GroupUpdate, request: Request):
    check_csrf(request)
    uid = validate_uid(uid)
    if payload.group is not None and payload.group not in GROUPS:
        raise HTTPException(422, 'Ungueltige Zugriffsgruppe')
    if uid == (request.session.get('user') or {}).get('sub'):
        raise HTTPException(409, 'Eigene Gruppe kann nicht geaendert werden')
    async with KeycloakAdmin() as kc:
        current = await kc.user_groups(uid)
        if any(g.get('name') == 'Admins' for g in current) and payload.group != 'Admins':
            raise HTTPException(409, 'Admin-Konten nur in der Keycloak-Konsole herabstufen')
        await kc.set_group(uid, payload.group)
        await kc.request('POST', f'users/{uid}/logout')
    audit(request, 'set_group_' + payload.group if payload.group is not None else 'remove_group', uid)
    return {'id': uid, 'group': payload.group}

@router.post('/users/{uid}/logout')
async def logout_user(uid: str, request: Request):
    check_csrf(request)
    uid = validate_uid(uid)
    async with KeycloakAdmin() as kc:
        await kc.request('POST', f'users/{uid}/logout')
    audit(request, 'logout_user', uid)
    return {'id': uid}

@router.post('/users/{uid}/reset-otp')
async def reset_otp(uid: str, request: Request):
    check_csrf(request)
    uid = validate_uid(uid)
    async with KeycloakAdmin() as kc:
        user = await kc.request('GET', f'users/{uid}')
        actions = list(set(user.get('requiredActions') or []) | {'CONFIGURE_TOTP'})
        await kc.request('PUT', f'users/{uid}', json={'requiredActions': actions})
        for credential in await kc.request('GET', f'users/{uid}/credentials'):
            if credential.get('type') == 'otp':
                from urllib.parse import quote
                await kc.request('DELETE', f'users/{uid}/credentials/{quote(credential["id"], safe="")}')
        await kc.request('POST', f'users/{uid}/logout')
    audit(request, 'reset_otp', uid)
    return {'id': uid}
