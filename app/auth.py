"""OpenID-Connect-Login gegen Keycloak (via authlib).

Der Login-Zustand liegt ausschliesslich in einem signierten, httponly
Session-Cookie (Starlette SessionMiddleware, siehe main.py) - es gibt
bewusst KEINEN serverseitigen Session-Store. Das passt zum Rest der
Anwendung (zustandslos, In-Memory-DB, austauschbare Container) und bedeutet:
ein Neustart der App invalidiert keine bestehenden Logins (das Cookie bleibt
gueltig, solange SECRET_KEY gleich bleibt), aber es gibt auch keine
serverseitige Moeglichkeit, eine einzelne Session vorzeitig zu widerrufen
(nur ueber Keycloak selbst, z.B. "Sessions beenden" in der Admin-Konsole).
"""
import logging
from urllib.parse import urlencode

from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(prefix="/auth", tags=["auth"])

oauth = OAuth()
if settings.oidc_configured:
    # Bewusst KEINE automatische Discovery (server_metadata_url), sondern
    # alle Endpunkte einzeln, explizit gesetzt - mit unterschiedlichen Hosts
    # fuer zwei unterschiedliche Zielgruppen:
    #
    #   - authorize_url: wird als Redirect-Ziel an den BROWSER geschickt.
    #     Muss die oeffentliche, ueber nginx erreichbare URL sein.
    #   - access_token_url / userinfo_endpoint / jwks_uri: werden vom
    #     APP-CONTAINER SELBST aufgerufen (Server-zu-Server). "localhost"
    #     waere hier der App-Container selbst, nicht nginx/Keycloak -
    #     deshalb die interne, direkte Docker-Netzwerk-Adresse.
    #
    # Ein einzelnes per Discovery geladenes Dokument koennte das nicht
    # abbilden (Keycloak liefert wegen des fest gesetzten KC_HOSTNAME immer
    # dieselbe - oeffentliche - Basis-URL fuer ALLE Endpunkte zurueck,
    # unabhaengig vom aufrufenden Kanal).
    #
    # issuer wird trotzdem auf die oeffentliche URL gesetzt: Keycloak traegt
    # wegen KC_HOSTNAME immer diese URL als "iss"-Claim in ausgestellte
    # Tokens ein, unabhaengig davon, ueber welchen Kanal der Token-Tausch
    # tatsaechlich lief - die Claim-Validierung muss also darauf pruefen.
    internal_base = settings.oidc_issuer_internal or settings.oidc_issuer
    oauth.register(
        name="keycloak",
        client_id=settings.oidc_client_id,
        client_secret=settings.oidc_client_secret,
        authorize_url=f"{settings.oidc_issuer}/protocol/openid-connect/auth",
        access_token_url=f"{internal_base}/protocol/openid-connect/token",
        userinfo_endpoint=f"{internal_base}/protocol/openid-connect/userinfo",
        jwks_uri=f"{internal_base}/protocol/openid-connect/certs",
        issuer=settings.oidc_issuer,
        client_kwargs={"scope": "openid email profile"},
    )
else:
    logger.warning(
        "OIDC ist nicht konfiguriert (OIDC_ISSUER/OIDC_CLIENT_ID/OIDC_CLIENT_SECRET). "
        "Login-Routen sind inaktiv."
    )

# Pfade, die ohne Login erreichbar sein muessen: der Login-Flow selbst
# (sonst kaeme niemand mehr rein), statische Assets fuer die Login-Seite
# und der Healthcheck fuer Docker/Monitoring.
PUBLIC_PATH_PREFIXES = ("/auth/", "/static/")
PUBLIC_PATHS = {"/healthz"}


class LoginRequiredMiddleware(BaseHTTPMiddleware):
    """Erzwingt einen gueltigen Keycloak-Login fuer alle uebrigen Routen.

    Greift nur, wenn AUTH_ENABLED=true (Default, siehe config.py) - der
    Fail-Fast-Check in main.py stellt sicher, dass dieser Zustand nur
    zusammen mit vollstaendig konfiguriertem OIDC erreicht wird.
    """

    async def dispatch(self, request: Request, call_next):
        if not settings.auth_enabled:
            return await call_next(request)

        path = request.url.path
        if path in PUBLIC_PATHS or path.startswith(PUBLIC_PATH_PREFIXES):
            return await call_next(request)

        if not request.session.get("user"):
            next_qs = urlencode({"next": path})
            return RedirectResponse(url=f"/auth/login?{next_qs}")

        return await call_next(request)


@router.get("/login")
async def login(request: Request, next: str = "/"):
    # Offener Redirect vermeiden: nur pfadrelative Ziele innerhalb der
    # eigenen App zulassen, keine absoluten/fremden URLs aus dem Query-Param.
    safe_next = next if next.startswith("/") and not next.startswith("//") else "/"
    request.session["post_login_redirect"] = safe_next

    redirect_uri = str(request.url_for("auth_callback"))
    return await oauth.keycloak.authorize_redirect(request, redirect_uri)


@router.get("/callback", name="auth_callback")
async def callback(request: Request):
    token = await oauth.keycloak.authorize_access_token(request)
    userinfo = token.get("userinfo") or await oauth.keycloak.userinfo(token=token)

    request.session["user"] = {
        "sub": userinfo.get("sub"),
        "email": userinfo.get("email"),
        "name": userinfo.get("name") or userinfo.get("preferred_username"),
    }
    # id_token wird fuer den vollstaendigen Logout (End-Session bei Keycloak,
    # nicht nur lokal) gebraucht.
    request.session["id_token"] = token.get("id_token")

    destination = request.session.pop("post_login_redirect", "/")
    return RedirectResponse(url=destination)


@router.get("/logout")
async def logout(request: Request):
    id_token = request.session.pop("id_token", None)
    request.session.clear()

    if not settings.oidc_configured:
        return RedirectResponse(url="/")

    # Wie bei authorize_url (siehe oben): end_session_endpoint ist ein
    # Redirect-Ziel fuer den BROWSER, muss also die oeffentliche URL sein.
    end_session_endpoint = f"{settings.oidc_issuer}/protocol/openid-connect/logout"
    params = {"post_logout_redirect_uri": str(request.url_for("index"))}
    if id_token:
        params["id_token_hint"] = id_token
    return RedirectResponse(url=f"{end_session_endpoint}?{urlencode(params)}")


@router.get("/me")
async def me(request: Request):
    """Kleiner Debug-/Statusendpunkt: zeigt, wer laut Session eingeloggt ist."""
    return request.session.get("user") or {"authenticated": False}
