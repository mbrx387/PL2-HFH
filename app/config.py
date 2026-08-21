"""Zentrale Konfiguration der Anwendung.

Alle Werte kommen ueber Umgebungsvariablen (siehe .env.example) und damit
ueber Docker Compose / systemd-Umgebungsdateien auf dem Ubuntu-Server rein.
Es werden bewusst KEINE Secrets im Code oder in diesem Repository abgelegt.
"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Pflegezentren-Finder"
    environment: str = "development"  # development | production
    log_level: str = "info"

    # Kommagetrennte Liste erlaubter Origins fuer CORS (nur relevant, falls die
    # API von einem separaten Frontend-Origin aus angesprochen wird).
    allowed_origins: str = "http://localhost:8000"

    # Pfad zur Seed-Datei, aus der die In-Memory-Datenbank beim Start befuellt wird.
    data_file: str = "app/data/pflegestellen.csv"

    # Schluessel zum Signieren des Session-Cookies (Login-Zustand). MUSS in
    # der Produktivumgebung ueberschrieben werden - siehe main.py, wo bei
    # is_production der unveraenderte Default hart abgelehnt wird.
    secret_key: str = "insecure-dev-secret-change-me"

    # Login-Pflicht fuer die gesamte Anwendung (ausser /auth/*, /static/*,
    # /healthz). Default = an (secure by default). Fuer schnelle lokale
    # UI-/Datenexploration ohne Keycloak explizit auf false setzen - siehe
    # README/ROADMAP fuer die Begruendung und den Bootstrapping-Ablauf.
    auth_enabled: bool = True

    # OIDC-Zugangsdaten fuer die Keycloak-Anbindung. Reihenfolge beim
    # erstmaligen Aufsetzen: Keycloak starten -> Client-Secret aus der
    # Admin-Konsole kopieren -> hier eintragen -> App (neu) starten.
    # Siehe docs/ROADMAP.md, Abschnitt 1.1.
    oidc_issuer: str | None = None
    oidc_client_id: str | None = None
    oidc_client_secret: str | None = None

    # Optional: abweichende Issuer-URL, unter der der APP-CONTAINER SELBST
    # Keycloak erreicht (Server-zu-Server: Discovery-Dokument, Token-Tausch,
    # Userinfo). "localhost" bedeutet im App-Container den App-Container
    # selbst, NICHT den nginx-Container - deshalb reicht OIDC_ISSUER (die
    # oeffentliche, browserseitige URL) hierfuer nicht aus. Faellt auf
    # OIDC_ISSUER zurueck, wenn nicht gesetzt (z.B. bei einem Setup ohne
    # Docker-Netzwerk-Trennung). Siehe app/auth.py.
    oidc_issuer_internal: str | None = None

    @property
    def allowed_origins_list(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"

    @property
    def oidc_configured(self) -> bool:
        return bool(self.oidc_issuer and self.oidc_client_id and self.oidc_client_secret)


@lru_cache
def get_settings() -> Settings:
    return Settings()
