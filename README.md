# PL2-HFH – Pflegezentren-Finder

Entwicklung einer Datenbank zur Bedarfsermittlung pflegender Angehöriger.

Dieses Repository enthält das **Grundgerüst** der Webanwendung: Sie zeigt
Pflege- und Beratungsstellen in Deutschland als filterbare Liste mit
Checkboxen an. Nutzer:innen wählen beliebig viele Stellen aus und lösen
darüber eine E-Mail über ihr **eigenes, lokal konfiguriertes Mailprogramm**
aus (Outlook, Apple Mail, Thunderbird, Web-Mail-Client des Betriebssystems
…) – der Server verschickt selbst keine Mails.

Dieses Dokument beschreibt vor allem **wie und warum** die Anwendung so
aufgebaut und gehostet ist. Das war der hier zu erbringende Teil des
Projekts; Datenmodell/Fachlogik werden im Team weiter ausgebaut (siehe
[Nächste Schritte](docs/ROADMAP.md)).

---

## 1. Architekturentscheidungen im Überblick

| Frage | Entscheidung | Warum |
|---|---|---|
| Framework | **FastAPI (Python)** | Klein, schnell erlernbar, automatische OpenAPI-Doku unter `/api/docs`, native Typvalidierung (Pydantic), asynchron-fähig, sehr verbreitet – gute Basis für ein Hochschulprojekt mit wechselnden Mitwirkenden. |
| Datenhaltung | **PostgreSQL über SQLAlchemy**, Tabellen `centers`, `services` und `center_services`; initialisiert aus dem ETL-CSV-Import | Persistente Daten und eine gemeinsame Datenquelle für App und Importjob. PostgreSQL bleibt nur im internen Compose-Netzwerk erreichbar. |
| Frontend | **Server-gerenderte Jinja2-Seite + Vanilla JS**, kein SPA-Framework | Kein Build-Schritt, kein Node-Toolchain-Overhead im Container, niedrige Einstiegshürde fürs Team, für den beschriebenen Funktionsumfang (Liste + Checkboxen + Filter) ausreichend. |
| Mailversand | **`mailto:`-Link im Browser** statt serverseitigem SMTP-Versand | Erfüllt die Vorgabe „über die eigene Standardmailbox versenden“ exakt, UND: der Server verarbeitet dadurch keine SMTP-Zugangsdaten, protokolliert keine E-Mail-Inhalte und hat keinen Angriffsvektor „Mailrelay-Missbrauch“. Sicherheits- und Datenschutzvorteil in einem. |
| Containerisierung | **Docker Compose** (nicht Swarm/Kubernetes) | Ein Ubuntu-Server, überschaubare Last, kleines Team. Docker Compose deckt „App + Reverse Proxy (+ optional SSO)“ vollständig ab, ohne die Betriebskomplexität eines Cluster-Orchestrators. Migration zu Swarm/K8s bleibt möglich, ist aber aktuell nicht gerechtfertigt (siehe Abschnitt 4). |
| Netzwerk-Exposition | **Nginx als TLS-Reverse-Proxy**, App-Container nur intern erreichbar | HTTPS-Terminierung, Security-Header, Rate-Limiting an einer zentralen Stelle statt in der Anwendung; die FastAPI-App selbst ist vom Host/Internet aus nicht direkt erreichbar. |
| Login/SSO | **Aktiv**: OpenID Connect gegen **Keycloak** (`docker-compose`-Profil `sso`), erzwungen über eine App-Middleware | Kein selbstgebautes Login (Passwort-Handling, Brute-Force-Schutz etc. sind fehleranfällig) – ein etablierter Open-Source-IdP übernimmt das. Details/Betrieb siehe [Abschnitt 5](#5-sicherheitskonzept) und [Roadmap](docs/ROADMAP.md). |

---

## 2. Projektstruktur

```
PL2-HFH/
├── app/                        # FastAPI-Anwendung (Python-Package "app")
│   ├── main.py                 # Einstiegspunkt, Startup/Lifespan, Routing, Middleware-Reihenfolge
│   ├── config.py                # Einstellungen aus Umgebungsvariablen (.env)
│   ├── database.py              # PostgreSQL-Engine und SQLAlchemy-Sessions
│   ├── models.py                 # ORM-Modelle Center, Service und Zuordnung
│   ├── schemas.py                # Pydantic-Response-Schemas
│   ├── security.py               # Security-Header-Middleware
│   ├── auth.py                   # OIDC-Login (Keycloak), Login-Pflicht-Middleware
│   ├── gunicorn_worker.py        # Proxy-Header-fähiger Uvicorn-Worker (siehe auth.py)
│   ├── routers/centers.py        # GET /api/centers, /api/bundeslaender
│   ├── data/pflegestellen.csv    # versionierter Ausgangs-/Demo-Datensatz
│   ├── templates/index.html      # Server-gerenderte Startseite
│   ├── static/css/style.css
│   ├── static/js/app.js          # Liste laden, filtern, mailto-Link bauen
│   ├── Dockerfile
│   └── requirements.txt
├── keycloak/realm-export.json    # Realm/Client/Rollen/Sicherheit, Import nur beim ersten Start
├── keycloak/configure.sh         # dieselben Einstellungen für einen bestehenden Realm (kcadm.sh)
├── nginx/
│   ├── nginx.conf
│   └── conf.d/default.conf       # TLS-Terminierung, Reverse Proxy, Rate-Limit, /idp/-Route (Keycloak)
├── scripts/generate_dev_cert.sh  # Self-signed Zertifikat für lokale Tests
├── tests/                        # Pytest (API, Auth-Middleware, Fail-Fast-Checks)
├── .github/workflows/deploy.yml  # CI: Lint + Tests -> Image-Build -> Deploy per SSH
├── docker-compose.yml
├── pyproject.toml                # ruff/pytest-Konfiguration
├── requirements-dev.txt
├── .env.example
└── docs/ROADMAP.md               # Umgesetzter Stand / nächste Schritte
```

## 3. Datenquelle

`app/data/pflegestellen.csv` ist ein versionierter Ausgangs-/Demo-Datensatz.
Der wöchentliche ETL-Workflow importiert neue Daten transaktional mit
`db/import_centers.sql` in die persistente PostgreSQL-Datenbank `app-db`.
Die Web-App liest direkt aus denselben Tabellen; sie lädt oder überschreibt
die Daten nicht beim Start. `unsere_id` wird als stabile `centers.id`
übernommen. Das PostgreSQL-Volume `app-db-data` bleibt über Container-Neustarts
erhalten.

## 4. Hosting-Konzept

**Zielumgebung:** ein einzelner Ubuntu-Server (vom Auftraggeber/der
Hochschule bereitgestellt), kein verteiltes Cluster.

```
Internet
   │  Port 443/80
   ▼
┌─────────────────────────────────────────┐
│ Ubuntu Server                            │
│                                          │
│  ┌────────────┐      ┌────────────────┐ │
│  │   nginx    │◄────►│   FastAPI-App   │ │
│  │ (TLS-Proxy)│      │ (Gunicorn+      │ │
│  │ Port 80/443│      │  Uvicorn-Worker)│ │
│  └────────────┘      └──────┬─────────┘ │
│                              │           │
│                       ┌──────▼─────────┐ │
│                       │    app-db       │ │
│                       │  PostgreSQL     │ │
│                       └────────────────┘ │
│        │ Compose-Profil "sso"            │
│  ┌────────────┐                          │
│  │  Keycloak  │  (Login, /idp/…)        │
│  └────────────┘                          │
│                                          │
│   docker network "internal" (bridge)     │
└─────────────────────────────────────────┘
```

**Warum Docker Compose statt Docker Swarm/Kubernetes?**
Wir haben einen einzelnen Server, ein kleines Team und einen überschaubaren
Funktionsumfang (eine Web-App + Reverse Proxy, perspektivisch + SSO). Ein
Cluster-Orchestrator bringt hier nur zusätzliche Betriebskomplexität
(Multi-Node-Netzwerke, Secrets-Management, Rolling-Update-Mechanik) ohne
echten Nutzen – es gibt nichts zu skalieren oder auszufallsichern. Docker
Compose deckt die Anforderungen (mehrere Container, definierte Startreihenfolge,
internes Netzwerk, Healthchecks, Ressourcenlimits, `.env`-basierte
Konfiguration) vollständig ab und ist für ein Hochschulteam ohne dedizierten
Infra-Betrieb deutlich wartbarer. Sollte die Anwendung später mehrere Server
oder Hochverfügbarkeit brauchen, ist der Umstieg auf Swarm/Kubernetes
möglich, aber aktuell nicht durch einen echten Bedarf gedeckt (YAGNI).

**Warum ist die FastAPI-App nicht direkt am Host-Port exponiert?**
Nur `nginx` published Ports 80/443 an den Host; die App ist ausschließlich
im internen Docker-Netzwerk erreichbar (`expose`, nicht `ports`). Damit läuft
jeglicher öffentliche Traffic zwingend durch die TLS-Terminierung und die
Security-/Rate-Limiting-Regeln von nginx, bevor er die Anwendung erreicht.

**Warum Gunicorn+Uvicorn-Worker statt `uvicorn --reload`?**
`--reload` ist ein Entwicklungs-Feature. Im Produktivbetrieb sorgt Gunicorn
für Prozess-Management (mehrere Worker-Prozesse, Neustart bei Absturz,
Timeouts) – Standardmuster für FastAPI-Deployments.

## 5. Sicherheitskonzept

Da personenbezogene/institutionelle Kontaktdaten (E-Mail-Adressen von
Beratungsstellen) verarbeitet werden und die Anwendung öffentlich erreichbar
sein wird, war Sicherheit von Anfang an Teil des Grundgerüsts, nicht
nachträglich aufgesetzt:

- **HTTPS/TLS**: Terminierung in nginx. Für den Produktivbetrieb auf dem
  Ubuntu-Server wird ein echtes Zertifikat über **Let's Encrypt / certbot**
  bezogen (siehe [Roadmap](docs/ROADMAP.md) – im Grundgerüst liegt dafür ein
  Script für ein selbstsigniertes Dev-Zertifikat bereit:
  `scripts/generate_dev_cert.sh`). HTTP wird per 301 auf HTTPS umgeleitet,
  `Strict-Transport-Security` ist gesetzt.
- **Security-Header**: `X-Content-Type-Options`, `X-Frame-Options`,
  `Content-Security-Policy`, `Referrer-Policy`, `Permissions-Policy` werden
  in der Anwendung selbst gesetzt (`app/security.py`) – unabhängig vom
  Auth-Konzept sinnvoll.
- **Kein serverseitiger Mailversand**: Der `mailto:`-Ansatz bedeutet, es
  gibt keine SMTP-Zugangsdaten im System, keine serverseitige Mail-Historie
  und keinen Vektor für Mailrelay-Missbrauch/Spam über die Anwendung.
- **Least Privilege im Container**: Der App-Container läuft als
  Non-Root-User, das Dateisystem ist `read_only` (nur `/tmp` beschreibar via
  `tmpfs`), Ressourcenlimits (CPU/RAM) sind gesetzt.
- **Keine Secrets im Repository**: Konfiguration ausschließlich über `.env`
  (siehe `.env.example`), `.env` ist in `.gitignore`.
- **Rate-Limiting** auf nginx-Ebene gegen automatisiertes Abgreifen der
  Kontaktliste oder Missbrauch der Such-API.
- **Server-seitige Begrenzung der Listengröße** (`limit`/`max 500` pro
  API-Aufruf) – niemand kann den kompletten Datensatz in einem Request
  abziehen.
- **Login/SSO über Keycloak (OpenID Connect), erzwungen für die gesamte
  App**: `app/auth.py` registriert einen OIDC-Client (via `authlib`) und
  hängt eine `LoginRequiredMiddleware` vor `/` und `/api/*` – ohne gültige,
  signierte Session (Login bei Keycloak) kommt niemand rein. Ausgenommen
  sind nur der Login-Flow selbst (`/auth/*`), statische Assets und
  `/healthz`. Kein selbstgebautes Passwort-Handling: Authentifizierung,
  Brute-Force-Schutz, Passwort-Reset laufen komplett über Keycloak.
- **Fail-fast statt fail-open**: Ist `AUTH_ENABLED=true` (Default) gesetzt,
  aber OIDC nicht vollständig konfiguriert, **startet die App absichtlich
  gar nicht** – lieber ein sofort sichtbarer Fehler beim Start als eine
  unbemerkt offene Anwendung. Für schnelle lokale UI-Exploration ohne
  Keycloak kann `AUTH_ENABLED=false` gesetzt werden (mit lauter Warnung im
  Log) – nicht für den Produktivbetrieb. Genauso wird ein unveränderter
  `SECRET_KEY` (signiert das Session-Cookie) im Produktivmodus abgelehnt.
- Betriebsanleitung für Keycloak (Realm-Import, Client-Secret, Bootstrapping-
  Reihenfolge) steht in [Abschnitt 8](#8-server-inbetriebnahme).

## 6. Bekannte Einschränkungen (aktueller Stand)

- `mailto:`-Links haben in der Praxis ein Längenlimit (abhängig vom
  Mailprogramm, z.B. Outlook ~1.800–2.000 Zeichen). Bei sehr großer Auswahl
  kann das an Grenzen stoßen – Warnhinweis/Split ist als nächster Schritt
  vorgesehen.
- Der Login-Zustand liegt nur im signierten Session-Cookie, es gibt keinen
  serverseitigen Session-Store. Ein einzelner Login lässt sich damit nicht
  vorzeitig serverseitig widerrufen (nur über Keycloak selbst, „Sessions
  beenden“ in der Admin-Konsole).
- Es gibt noch keine Rollen-/Rechteprüfung – jeder erfolgreiche Keycloak-
  Login hat vollen Zugriff auf alle Funktionen. Für ein reines
  Beratungsstellen-Verzeichnis vertretbar, sollte aber vor produktivem
  Einsatz mit sensibleren Daten überdacht werden.
- Nutzerbezogene Zustände (z.B. „gemerkte Auswahl über Sessions hinweg“) gibt
  es noch nicht. Die Verzeichnisdaten selbst liegen persistent in PostgreSQL.

## 7. Lokal starten

Da Login jetzt erzwungen wird (Abschnitt 5), braucht der vollständige Start
Keycloak *vor* der App. Server-Variante: [Abschnitt 8](#8-server-inbetriebnahme).

**A) Vollständig, mit Login (entspricht dem Zielsetup):**

```bash
cp .env.example .env
# In .env setzen: SECRET_KEY, APP_DB_PASSWORD,
# KEYCLOAK_ADMIN_PASSWORD, KEYCLOAK_DB_PASSWORD
# (je: openssl rand -base64 32), ausserdem fuer lokal:
#   APP_PUBLIC_URL=https://localhost
#   KC_HOSTNAME=https://localhost/idp
#   KC_COMMAND=start-dev
#   OIDC_ISSUER=https://localhost/idp/realms/hfh-pflege
#   ALLOWED_ORIGINS=https://localhost
./scripts/generate_dev_cert.sh          # einmalig, selbstsigniertes Dev-Zertifikat

docker compose --profile sso up -d keycloak   # 1) nur Keycloak (+ DB) starten
# Client-Secret kopieren: http://localhost:8080/idp/admin/ (admin / dein
# KEYCLOAK_ADMIN_PASSWORD) -> Realm "hfh-pflege" -> Clients -> pflege-finder
# -> Credentials -> Client secret. In .env als OIDC_CLIENT_SECRET eintragen.

docker compose --profile sso up -d --build    # 2) jetzt App + nginx starten
# Beim ersten Start die Datenbank einmal befuellen:
docker compose cp app/data/pflegestellen.csv app-db:/tmp/pflegestellen.csv
docker compose exec -T app-db psql -v ON_ERROR_STOP=1 -U pl2 -d pflegedb \
  < db/import_centers.sql
# -> https://localhost (Zertifikatswarnung ist bei selbstsigniertem Zertifikat normal)
# -> Login-Redirect zu Keycloak. Es gibt kein Demo-Konto: ein Konto in der
#    Admin-Konsole anlegen und einer Gruppe zuordnen (siehe Abschnitt 8).
```

**B) Schnell, ohne Login (nur lokale UI-/Datenexploration):**

```bash
cp .env.example .env
sed -i 's/AUTH_ENABLED=true/AUTH_ENABLED=false/' .env
./scripts/generate_dev_cert.sh
docker compose up --build       # kein --profile sso nötig
# Beim ersten Start die Datenbank einmal befuellen:
docker compose cp app/data/pflegestellen.csv app-db:/tmp/pflegestellen.csv
docker compose exec -T app-db psql -v ON_ERROR_STOP=1 -U pl2 -d pflegedb \
  < db/import_centers.sql
# -> https://localhost, ohne Login erreichbar (Warnung dazu steht im Log)
```

**Ohne Docker, nur für schnelle Backend-Entwicklung:**

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r app/requirements.txt -r requirements-dev.txt
# PostgreSQL muss laufen, initialisiertes Schema und APP_DB_PASSWORD in .env.
AUTH_ENABLED=false uvicorn app.main:app --reload
# -> http://localhost:8000
```

**Tests und Lint** (laufen in CI vor jedem Build/Deploy, auch für Pull Requests):

```bash
ruff check . && pytest
```

API-Dokumentation (Swagger UI) liegt automatisch unter `/api/docs` (ebenfalls
login-pflichtig, sobald `AUTH_ENABLED=true`).

## 8. Server-Inbetriebnahme

Deploys laufen automatisch per GitHub Actions (`.github/workflows/deploy.yml`).
Einmalig auf dem Server nötig, weil das Keycloak-Client-Secret erst nach dem
Realm-Import existiert:

1. **`.env` anlegen** unter `/opt/pl2-hfh/.env` (Vorlage: `.env.example`),
   alle Werte außer `OIDC_CLIENT_SECRET` setzen. TLS-Zertifikat nach
   `nginx/certs/fullchain.pem` und `privkey.pem` legen.
2. **Keycloak starten:** `docker compose --profile sso up -d keycloak-db keycloak`
3. **Admin-Konsole per SSH-Tunnel** öffnen (öffentlich gesperrt):
   `ssh -L 8080:localhost:8080 <user>@<server>`, dann
   `http://localhost:8080/idp/admin/` (Benutzer `admin`).
4. **Einmalig: Login der Konsole auf den Tunnel umbiegen** – sonst leitet
   Keycloak den Admin-Login auf die öffentliche Domain um:
   ```bash
   docker compose exec -it keycloak /opt/keycloak/bin/kcadm.sh config credentials \
     --server http://localhost:8080/idp --realm master --user admin
   docker compose exec keycloak /opt/keycloak/bin/kcadm.sh update realms/master \
     -s 'attributes.frontendUrl=http://localhost:8080/idp'
   ```
5. **Client prüfen und Secret holen:** Realm `hfh-pflege` → Clients →
   `pflege-finder`
   - Settings: *Valid redirect URIs* `<APP_PUBLIC_URL>/auth/callback`,
     *Valid post logout redirect URIs* `<APP_PUBLIC_URL>/`
   - Credentials: *Client secret* kopieren und in `.env` als
     `OIDC_CLIENT_SECRET` eintragen.
6. **Benutzer und Rollen einrichten:** Im Realm `hfh-pflege` unter *Users* für jede
   Person ein eigenes Konto anlegen. Unter *Credentials* ein temporäres Passwort
   setzen und sicher über einen freigegebenen Kanal übermitteln. Danach unter
   *Groups* → *Join group* genau einer Gruppe zuordnen: `Lesend` (Rolle
   `reader`), `Redaktion` (`editor`) oder `Admins` (`admin`). Die Gruppen tragen
   die Client-Rollen des Clients `pflege-finder`. Keine gemeinsamen Konten
   verwenden; ein Demo-Konto gibt es nicht mehr. Neue Konten müssen beim ersten
   Login einen Einmalcode (OTP-App) einrichten.
   - `reader`: Verzeichnis lesen.
   - `editor`: lesen, anlegen, ändern und Stellen deaktivieren.
   - `admin`: dieselben Verzeichnisrechte wie `editor`; eine Nutzerverwaltung in
     der App gibt es nicht.
   - Die Client-Rolle `admin` verleiht **keine** Rechte in der Keycloak-Konsole.
     Personen, die Konten verwalten sollen, benötigen dafür eine separat und
     gezielt freigegebene Keycloak-Berechtigung im Realm `hfh-pflege`. Den
     globalen `master`-Admin nicht für den täglichen Betrieb verwenden.
   - Rollenänderungen werden nach erneutem Login wirksam; die App-Sitzung kann
     bis zu acht Stunden bestehen. Für sofortige Wirkung abmelden und erneut anmelden.
   - Konten deaktivieren: Benutzerkonto in Keycloak öffnen und *Enabled*
     ausschalten. Passwort zurücksetzen: *Credentials* → Passwort zurücksetzen;
     E-Mail-Reset funktioniert nur mit eingerichteter Keycloak-Mail-Konfiguration.
7. **Deploy erneut auslösen** (Actions → „Re-run failed jobs“) oder
   `docker compose --profile sso up -d`.

### Keycloak-Einstellungen: Realm-Datei, Skript, manuell

`keycloak/realm-export.json` enthält alle Sicherheits- und Rollen-Einstellungen,
wird aber **nur beim allerersten Start** (leere Keycloak-Datenbank) importiert.
Für einen bestehenden Realm setzt `keycloak/configure.sh` dieselben Werte per
`kcadm.sh`; das Skript kann beliebig oft laufen.

| Situation | Was zu tun ist |
|---|---|
| Normales Deployment (Push auf `main`) | Nichts. Die Einstellungen liegen in `keycloak-db`. |
| Einstellungen in der Realm-Datei geändert | `./keycloak/configure.sh` auf dem Server ausführen (und das Skript mitpflegen). |
| Neuer Server / leeres Volume | Schritte 1–7 oben, danach einmal `./keycloak/configure.sh`. |

```bash
cd /opt/pl2-hfh
./keycloak/configure.sh                 # fragt das Admin-Passwort ab
./keycloak/configure.sh --delete-demo   # entfernt zusätzlich ein altes Demo-Konto
./keycloak/configure.sh --enforce-pkce  # erst NACH dem Deploy der App-Version mit PKCE
```

Was die Realm-Datei und das Skript setzen:

| Einstellung | Wert | Realm-Datei | Skript |
|---|---|---|---|
| Schutz gegen Passwort-Raten | Sperre nach 5 Fehlversuchen, +60 s je Versuch, max. 15 min | ja | ja |
| Passwort-Richtlinie | mind. 12 Zeichen, nicht Benutzername/E-Mail, Historie 3 | ja | ja |
| „Passwort vergessen“ | aus, bis E-Mail-Versand eingerichtet ist | ja | ja |
| „Angemeldet bleiben“ | aus | ja | ja |
| Sprache | Deutsch (Standard), Englisch | ja | ja |
| Sitzungen | 30 min Leerlauf, max. 8 h, Access-Token 5 min | ja | ja |
| Audit-Protokoll | Benutzer- und Admin-Events, 30 Tage | ja | ja |
| Client-Rollen `reader`/`editor`/`admin`, Claim `roles` | wie in `app/auth.py` erwartet | ja | ja |
| Gruppen `Lesend`/`Redaktion`/`Admins` | tragen je eine Rolle | ja | ja |
| „Full scope allowed“ | aus (nur eigene Rollen im Token) | ja | ja |
| PKCE (S256) | erzwungen | ja | nur mit `--enforce-pkce` |
| Einmalcode (OTP) für neue Konten | Pflicht beim ersten Login | nein | ja |
| Login-Schutz im Realm `master` | wie oben | nein | ja |

Immer manuell (stehen bewusst nicht im Repository): Secrets in der `.env`,
Client-Secret aus der Konsole übernehmen (Schritt 5), `frontendUrl` des
`master`-Realms (Schritt 4), persönliche Admin-Konten, echte Benutzer und ihre
Gruppen, TLS-Zertifikat, Backups.

Fehlt etwas in der `.env`, bricht der Deploy-Job mit einer Meldung ab, die die
fehlenden Variablen benennt.

---

Umgesetzter Stand und nächste Schritte: siehe [`docs/ROADMAP.md`](docs/ROADMAP.md).
