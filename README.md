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
| Datenhaltung | **In-Memory-SQLite über SQLAlchemy**, befüllt aus einer versionierten CSV-Datei | Kein eigener DB-Server nötig (Vorgabe: „kein MySQL-Server o.ä.“), aber trotzdem echtes SQL (Filtern/Suchen/Sortieren) statt Handstricken auf Listen. Migration auf Postgres/MySQL später ist nur ein Wechsel der Connection-URL, da über SQLAlchemy-Modelle gearbeitet wird. |
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
│   ├── database.py              # In-Memory-SQLite-Engine (SQLAlchemy)
│   ├── models.py                 # ORM-Modell "Center"
│   ├── schemas.py                # Pydantic-Response-Schemas
│   ├── seed.py                   # Befüllt die DB aus app/data/*.csv beim Start
│   ├── security.py               # Security-Header-Middleware
│   ├── auth.py                   # OIDC-Login (Keycloak), Login-Pflicht-Middleware
│   ├── gunicorn_worker.py        # Proxy-Header-fähiger Uvicorn-Worker (siehe auth.py)
│   ├── routers/centers.py        # GET /api/centers, /api/bundeslaender
│   ├── data/pflegestellen.csv    # Seed-/Demodaten (Quelle der Wahrheit)
│   ├── templates/index.html      # Server-gerenderte Startseite
│   ├── static/css/style.css
│   ├── static/js/app.js          # Liste laden, filtern, mailto-Link bauen
│   ├── Dockerfile
│   └── requirements.txt
├── keycloak/realm-export.json    # Realm/Client/Demo-User, automatischer Import
├── nginx/
│   ├── nginx.conf
│   └── conf.d/default.conf       # TLS-Terminierung, Reverse Proxy, Rate-Limit, /idp/-Route (Keycloak)
├── scripts/generate_dev_cert.sh  # Self-signed Zertifikat für lokale Tests
├── docker-compose.yml
├── .env.example
└── docs/ROADMAP.md               # Nächste Schritte / offene Punkte
```

## 3. Datenquelle

`app/data/pflegestellen.csv` enthält ~4.090 Beratungs-/Pflegestellen
(Name, Adresse, PLZ/Ort/Bundesland, Kontakt, Geokoordinaten, Angebotsarten)
aus dem Datenimport im Branch `pflegestellen` dieses Repos. Sie dient hier
als realistischer Demo-/Startdatensatz für das Grundgerüst. Die Datei ist
bewusst versioniert (statt z.B. in einem Volume abgelegt): Sie ist die
**Quelle der Wahrheit**, aus der die In-Memory-Datenbank bei jedem
Containerstart neu aufgebaut wird. Das macht App-Instanzen zustandslos und
austauschbar und macht "Datenverlust bei Neustart" (typisches Risiko einer
In-Memory-DB) irrelevant.

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
│  └────────────┘      │  In-Memory-DB   │ │
│        ▲              └────────────────┘ │
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
  Reihenfolge) steht in [`docs/ROADMAP.md`](docs/ROADMAP.md), Abschnitt 1.1.

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
- Die In-Memory-Datenbank verliert ihren Zustand bei jedem Neustart –
  gewollt, da sie aus der versionierten CSV neu aufgebaut wird. Nutzerbezogene
  Zustände (z.B. „gemerkte Auswahl über Sessions hinweg“) gibt es entsprechend
  noch nicht.

## 7. Lokal starten

Da Login jetzt erzwungen wird (Abschnitt 5), braucht der vollständige Start
Keycloak *vor* der App. Details/Begründung: [`docs/ROADMAP.md`](docs/ROADMAP.md), Abschnitt 1.1.

**A) Vollständig, mit Login (entspricht dem Zielsetup):**

```bash
cp .env.example .env
# SECRET_KEY und KEYCLOAK_ADMIN_PASSWORD in .env auf zufällige Werte setzen,
# z.B. jeweils: openssl rand -base64 32
./scripts/generate_dev_cert.sh          # einmalig, selbstsigniertes Dev-Zertifikat

docker compose --profile sso up -d keycloak   # 1) nur Keycloak starten
# Client-Secret kopieren: http://localhost:8080/idp/admin/ (admin / dein
# KEYCLOAK_ADMIN_PASSWORD) -> Realm "hfh-pflege" -> Clients -> pflege-finder
# -> Credentials -> Client secret. In .env als OIDC_CLIENT_SECRET eintragen,
# OIDC_ISSUER auf https://localhost/idp/realms/hfh-pflege setzen.

docker compose --profile sso up -d --build    # 2) jetzt App + nginx starten
# -> https://localhost (Zertifikatswarnung ist bei selbstsigniertem Zertifikat normal)
# -> Login-Redirect zu Keycloak; Demo-Zugang: demo / demo1234
```

**B) Schnell, ohne Login (nur lokale UI-/Datenexploration):**

```bash
cp .env.example .env
sed -i 's/AUTH_ENABLED=true/AUTH_ENABLED=false/' .env
./scripts/generate_dev_cert.sh
docker compose up --build       # kein --profile sso nötig
# -> https://localhost, ohne Login erreichbar (Warnung dazu steht im Log)
```

**Ohne Docker, nur für schnelle Backend-Entwicklung:**

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r app/requirements.txt
AUTH_ENABLED=false uvicorn app.main:app --reload
# -> http://localhost:8000
```

API-Dokumentation (Swagger UI) liegt automatisch unter `/api/docs` (ebenfalls
login-pflichtig, sobald `AUTH_ENABLED=true`).

---

Nächste Schritte und offene Diskussionspunkte: siehe [`docs/ROADMAP.md`](docs/ROADMAP.md).
