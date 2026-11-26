"""FastAPI-Einstiegspunkt mit PostgreSQL-Schema-Pruefung und App-Routing."""
import logging
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import inspect
from starlette.middleware.sessions import SessionMiddleware

from app.auth import LoginRequiredMiddleware, has_permission
from app.auth import router as auth_router
from app.config import get_settings, is_placeholder
from app.database import engine
from app.mail_models import ensure_mail_history_table
from app.routers import admin, centers, mail
from app.security import SecurityHeadersMiddleware

settings = get_settings()

logging.basicConfig(level=settings.log_level.upper())
logger = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Fail-Fast statt fail-open: eine Anwendung, die Logins erzwingen soll,
    # aber nicht kann (weil Keycloak-Zugangsdaten fehlen), startet lieber gar
    # nicht, als unbemerkt offen zu laufen. Siehe README/ROADMAP fuer den
    # Bootstrapping-Ablauf (Keycloak zuerst, dann Secret eintragen).
    if settings.auth_enabled and not settings.oidc_configured:
        raise RuntimeError(
            "AUTH_ENABLED=true, aber OIDC_ISSUER/OIDC_CLIENT_ID/OIDC_CLIENT_SECRET sind "
            "nicht vollstaendig gesetzt. Entweder Keycloak zuerst hochfahren "
            "('docker compose --profile sso up -d keycloak'), das Client-Secret aus der "
            "Admin-Konsole in .env eintragen (siehe README.md, Abschnitt 8) und die "
            "App neu starten - oder fuer lokale Entwicklung ohne Login AUTH_ENABLED=false "
            "setzen (NICHT fuer den Produktivbetrieb)."
        )
    if settings.keycloak_admin_enabled and (
        not settings.auth_enabled
        or is_placeholder(settings.keycloak_admin_client_id)
        or is_placeholder(settings.keycloak_admin_client_secret)
    ):
        raise RuntimeError("Admin-Schalter erfordert AUTH_ENABLED und Admin-Client-Zugangsdaten.")
    
    if settings.is_production and settings.secret_key_is_weak:
        raise RuntimeError(
            "SECRET_KEY ist ein Platzhalter oder kuerzer als 32 Zeichen - das darf im "
            "Produktivbetrieb nicht passieren, da sich sonst Session-Cookies faelschen "
            "liessen. Bitte in .env einen zufaelligen Wert setzen, z.B. "
            "'openssl rand -base64 32'."
        )
    if not settings.auth_enabled:
        logger.warning(
            "AUTH_ENABLED=false: Die Anwendung laeuft OHNE Login-Pflicht. Nur fuer lokale "
            "Entwicklung geeignet, NICHT fuer den Produktivbetrieb!"
        )

    if not settings.database_url and not settings.app_db_password:
        raise RuntimeError(
            "APP_DB_PASSWORD fehlt. PostgreSQL-Verbindung in .env konfigurieren "
            "oder DATABASE_URL fuer lokale Tests setzen."
        )
    required_tables = {"centers", "services", "center_services"}
    with engine.connect() as connection:
        existing_tables = set(inspect(connection).get_table_names())
    missing_tables = required_tables - existing_tables
    if missing_tables:
        raise RuntimeError(
            "PostgreSQL-Schema unvollstaendig; fehlende Tabellen: "
            + ", ".join(sorted(missing_tables))
        )
    # AP5: Die einzige Tabelle, die die App selbst anlegt - und nur, falls sie
    # fehlt. db/init/ wirkt bei bestehenden Volumes nicht mehr. Details:
    # app/mail_models.py und docs/AP5_EMAIL_HISTORY.md.
    ensure_mail_history_table(engine)
    logger.info("PostgreSQL-Verbindung und Schema sind bereit.")
    yield
    engine.dispose()


app = FastAPI(
    title=settings.app_name,
    description=(
        "Findet Pflege-/Beratungsstellen in Deutschland und erlaubt den Versand einer "
        "Sammel-Mail ueber die Standard-Mailbox der Nutzer:innen."
    ),
    version="0.1.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

# Reihenfolge ist hier wichtig: Starlette wrapped Middleware so, dass die
# ZULETZT hinzugefuegte aussen liegt und ihre dispatch()-Logik zuerst fuer
# eingehende Requests laeuft (empirisch verifiziert - nicht "erste
# hinzugefuegte laeuft zuerst", wie man intuitiv vermuten koennte).
# SessionMiddleware muss deshalb NACH LoginRequiredMiddleware registriert
# werden, damit sie als aeussere Schicht zuerst laeuft und request.session
# befuellt, BEVOR LoginRequiredMiddleware es liest.
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)
app.add_middleware(LoginRequiredMiddleware)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    same_site="lax",
    https_only=settings.is_production,
    max_age=60 * 30,  # 30 Minuten
)

app.include_router(auth_router)
app.include_router(centers.router)
app.include_router(mail.router)
if settings.auth_enabled and settings.keycloak_admin_enabled:
    app.include_router(admin.router)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")


def _asset_version() -> str:
    """Versions-Parameter fuer CSS/JS-Links (?v=...).

    nginx cacht /static/-Dateien MIT diesem Parameter ein Jahr lang
    (nginx/nginx.conf, map $static_cache_control). Jeder Deploy setzt einen
    neuen IMAGE_TAG (sha-<commit>), dadurch aendert sich die URL und Browser
    laden die neue Datei. Ohne echten Tag (lokal, "latest") der Startzeitpunkt.
    """
    tag = os.getenv("IMAGE_TAG", "").strip()
    return tag if tag and tag != "latest" else str(int(time.time()))


templates.env.globals["asset_version"] = _asset_version()


@app.get("/healthz", tags=["meta"])
def healthz():
    """Wird vom Docker-Healthcheck und ggf. einem Load Balancer abgefragt."""
    return {"status": "ok"}


ROLE_LABELS = {"admin": "Administration", "editor": "Redaktion", "reader": "Lesezugriff"}


@app.get("/")
def index(request: Request):
    user = request.session.get("user") if settings.auth_enabled else None
    # Nur fuer die Anzeige (Menuepunkt "Datenpflege" ein-/ausblenden); die
    # eigentliche Pruefung passiert serverseitig in require_permission().
    can_edit = has_permission(user, "write_centers") if settings.auth_enabled else True
    # Eigene Berechtigung für Benutzerverwaltung
    can_manage_users = (
        settings.auth_enabled and settings.keycloak_admin_enabled and has_permission(user, "manage_users")
    )
    # CSRF-Token pro Sitzung, nur fuer Admin-Formulare
    import secrets
    if can_manage_users and 'admin_csrf' not in request.session:
        request.session['admin_csrf'] = secrets.token_urlsafe(32)
    roles = (user or {}).get("roles") or []
    role_label = next((ROLE_LABELS[r] for r in ("admin", "editor", "reader") if r in roles), "")
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "app_name": settings.app_name,
            "user": user,
            "can_edit": can_edit,
            #Berechtigung ans Template übergeben
            "can_manage_users": can_manage_users,
            #CSRF-Token im Template
            "admin_csrf": request.session.get("admin_csrf", "") if can_manage_users else "",
            "account_url": (
                (settings.oidc_issuer or "").rstrip("/") + "/account/"
                if settings.auth_enabled and settings.oidc_issuer
                else None
            ),
            "role_label": role_label if settings.auth_enabled else "Entwicklung",
        },
    )
