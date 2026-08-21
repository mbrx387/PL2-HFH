"""FastAPI-Einstiegspunkt.

Startet die Anwendung, befuellt die In-Memory-DB aus der CSV-Seed-Datei und
haengt Router, Templates und Static Files ein.
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from app.auth import LoginRequiredMiddleware
from app.auth import router as auth_router
from app.config import get_settings
from app.database import Base, SessionLocal, engine
from app.routers import centers
from app.security import SecurityHeadersMiddleware
from app.seed import load_centers_from_csv

settings = get_settings()

logging.basicConfig(level=settings.log_level.upper())
logger = logging.getLogger("app")

DEFAULT_SECRET_KEY = "insecure-dev-secret-change-me"


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
            "Admin-Konsole in .env eintragen (siehe docs/ROADMAP.md, Abschnitt 1.1) und die "
            "App neu starten - oder fuer lokale Entwicklung ohne Login AUTH_ENABLED=false "
            "setzen (NICHT fuer den Produktivbetrieb)."
        )
    if settings.is_production and settings.secret_key == DEFAULT_SECRET_KEY:
        raise RuntimeError(
            "SECRET_KEY wurde nicht ueberschrieben (Default-Wert aus dem Code) - das darf im "
            "Produktivbetrieb nicht passieren, da sich sonst Session-Cookies faelschen "
            "liessen. Bitte in .env einen zufaelligen Wert setzen, z.B. "
            "'openssl rand -base64 32'."
        )
    if not settings.auth_enabled:
        logger.warning(
            "AUTH_ENABLED=false: Die Anwendung laeuft OHNE Login-Pflicht. Nur fuer lokale "
            "Entwicklung geeignet, NICHT fuer den Produktivbetrieb!"
        )

    # Schema anlegen und In-Memory-DB aus der Seed-CSV befuellen.
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        count = load_centers_from_csv(db, settings.data_file)
        logger.info("%s Eintraege in der In-Memory-DB verfuegbar.", count)
    finally:
        db.close()
    yield
    # Shutdown: nichts aufzuraeumen, da die DB rein im Arbeitsspeicher liegt.


app = FastAPI(
    title=settings.app_name,
    description="Findet Pflege-/Beratungsstellen in Deutschland und erlaubt den Versand einer Sammel-Mail ueber die Standard-Mailbox der Nutzer:innen.",
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
    allow_methods=["GET"],
    allow_headers=["*"],
)
app.add_middleware(LoginRequiredMiddleware)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    same_site="lax",
    https_only=settings.is_production,
    max_age=60 * 60 * 8,  # 8 Stunden
)

app.include_router(auth_router)
app.include_router(centers.router)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")


@app.get("/healthz", tags=["meta"])
def healthz():
    """Wird vom Docker-Healthcheck und ggf. einem Load Balancer abgefragt."""
    return {"status": "ok"}


@app.get("/")
def index(request: Request):
    user = request.session.get("user") if settings.auth_enabled else None
    return templates.TemplateResponse(
        request, "index.html", {"app_name": settings.app_name, "user": user}
    )
