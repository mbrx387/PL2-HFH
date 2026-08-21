# Nächste Schritte

Dieses Dokument sammelt, was auf das Grundgerüst aufbaut. Reihenfolge ist
grob priorisiert, aber im Team zu diskutieren.

## 1. Login / SSO — ✅ umgesetzt (App-seitig erzwungen)

Umgesetzt: **OpenID Connect gegen Keycloak** (Open-Source-Identity-Provider),
kein selbstgebautes Login. Sowohl Keycloak-Betrieb als auch die
App-seitige Durchsetzung (`LoginRequiredMiddleware` in `app/auth.py`) stehen.
Offene Punkte für den Produktivbetrieb siehe 1.1 B und 1.3.

- **Keycloak** (bereits als optionales Docker-Compose-Profil `sso`
  vorbereitet) – ausgereift, große Community, unterstützt OIDC/SAML,
  Rollen-/Gruppenverwaltung, bei Bedarf auch Anbindung an bestehende
  Hochschul-Logins (LDAP/SAML-Föderation).
- Alternative: **Authentik** – schlanker, moderne UI, ebenfalls OIDC-fähig.
  Sinnvoll, wenn Keycloak dem Team zu schwergewichtig ist.
- Anbindung in FastAPI z.B. über `authlib`: Login-Redirect zu Keycloak,
  Rückgabe eines Sessions-/JWT-Cookies, Absicherung der Endpunkte über eine
  FastAPI-Dependency (`Depends(current_user)`).
- Warum nicht selbst bauen? Passwort-Handling, Session-Fixation, Brute-Force-
  Schutz, Passwort-Reset-Flows etc. sind gut verstandene, aber
  fehleranfällige Themen – ein etablierter IdP nimmt uns das ab und ist für
  ein Hochschulprojekt auch fachlich die "richtige" Referenzlösung.

### 1.1 Keycloak in Betrieb nehmen – Schritt für Schritt

**A) Lokal/Dev (zum Ausprobieren, Realm-Import ist bereits vorbereitet)**

Wichtig: Die App startet mit `AUTH_ENABLED=true` (Default) absichtlich
**nicht**, solange OIDC nicht konfiguriert ist (Fail-Fast, siehe
`app/main.py`). Reihenfolge deshalb: erst Keycloak alleine hochfahren, dann
Secret eintragen, erst danach App + nginx starten.

1. `.env` aus `.env.example` ableiten (falls noch nicht geschehen), dabei
   `SECRET_KEY` und `KEYCLOAK_ADMIN_PASSWORD` auf zufällige Werte setzen
   (z.B. je `openssl rand -base64 32`).
2. Nur Keycloak starten: `docker compose --profile sso up -d keycloak`
   (App und nginx noch **nicht** mitstarten – die App würde ohne Secret
   sofort crash-loopen, das ist normal/erwartet, kein Bug). Beim ersten
   Start liest Keycloak automatisch `keycloak/realm-export.json` ein
   (`--import-realm`) und legt an:
   - Realm `hfh-pflege`
   - Client `pflege-finder` (confidential, OIDC, Redirect-URIs auf
     `localhost` vorkonfiguriert)
   - Demo-Nutzer `demo` / `demo1234` (Passwort muss beim ersten Login
     geändert werden)
3. Admin-Konsole öffnen: läuft standardmäßig **nur auf `127.0.0.1:8080`**
   (siehe `docker-compose.yml`), nicht öffentlich erreichbar. Lokal reicht
   `http://localhost:8080/idp/admin/`; auf dem Server per SSH-Tunnel:
   `ssh -L 8080:localhost:8080 <user>@<server>`.
4. Mit `admin` / dem gesetzten `KEYCLOAK_ADMIN_PASSWORD` einloggen, in den
   Realm `hfh-pflege` wechseln (oben links).
5. Client-Secret abholen: **Clients → pflege-finder → Credentials → Client
   secret** kopieren.
6. In `.env` eintragen (`OIDC_ISSUER` entspricht dem `/idp/`-Pfad, unter dem
   nginx Keycloak proxied - browserseitig, das ist die einzige URL, die
   Keycloak auch tatsächlich in seine eigenen Login-Seiten/Redirects
   einbaut. `OIDC_ISSUER_INTERNAL` ist bereits in `.env.example`
   vorbelegt und muss normalerweise nicht angepasst werden - sie zeigt auf
   den Keycloak-Container direkt im Docker-Netz, weil "localhost" aus Sicht
   des App-Containers der App-Container selbst wäre, siehe `app/auth.py`):
   ```
   OIDC_ISSUER=https://localhost/idp/realms/hfh-pflege
   OIDC_CLIENT_ID=pflege-finder
   OIDC_CLIENT_SECRET=<kopierter Wert>
   ```
7. Jetzt App + nginx (mit-)starten: `docker compose --profile sso up -d --build`
8. Funktionscheck: `https://localhost/` sollte sofort zu Keycloaks
   Login-Seite umleiten; nach Login mit `demo`/`demo1234` zurück auf die
   Pflegezentren-Seite mit sichtbarem „Angemeldet als …“-Hinweis oben rechts.

Vollständig End-to-End getestet und verifiziert (echter Browser-loser
Login-Roundtrip über curl: Formular-Login, Callback, Session-Cookie,
authentifizierter API-Zugriff, vollständiger SSO-Logout). Dabei wurden
mehrere reale Bugs gefunden und gefixt - Details siehe Git-Historie:
- nginx cached Container-IPs von `app`/`keycloak` dauerhaft; nach einem
  Neustart NUR eines der beiden Container zeigte nginx sonst ins Leere
  (502). Fix: `resolver` + Variablen statt statischer Hostnamen in
  `proxy_pass` (siehe `nginx/conf.d/default.conf`).
- Eigene App-Routen (`/auth/login` etc.) und Keycloaks HTTP-Pfad kollidierten
  beide auf `/auth/` - Keycloak läuft deshalb unter `/idp/` statt `/auth/`.
- `KC_HOSTNAME` ohne Pfad-Anteil ließ Keycloaks eigene Login-Formulare den
  `/idp`-Präfix verlieren - Fix: Pfad direkt in `KC_HOSTNAME` einbetten
  (`https://localhost/idp`, siehe `docker-compose.yml`).
- Server-zu-Server-Aufrufe (Token-Tausch, Userinfo) dürfen nicht über die
  öffentliche, browserseitige URL laufen - der App-Container versteht
  "localhost" als sich selbst. Fix: separate interne Endpunkt-URLs in
  `app/auth.py`, siehe `OIDC_ISSUER_INTERNAL`.

**B) Produktivbetrieb auf dem Ubuntu-Server**

Der aktuelle Compose-Service nutzt bewusst den einfachen Entwicklungsmodus
(`start-dev`, eingebaute H2-Datenbank, kein eigenes TLS). Für den echten
Betrieb vor dem Going-Live zusätzlich:

1. **Eigene Postgres-Datenbank** statt der eingebauten H2-DB: einen
   `keycloak-db`-Service (`postgres:16-alpine`) ergänzen, Keycloak über
   `KC_DB=postgres`, `KC_DB_URL`, `KC_DB_USERNAME`, `KC_DB_PASSWORD`
   anbinden. Grund: H2 ist nicht für Mehrbenutzer-/Dauerbetrieb gedacht und
   büßt Konsistenzgarantien ein.
2. **`start` statt `start-dev`** im `command:` – der Dev-Modus deaktiviert
   u.a. Cache-Optimierungen und toleriert absichtlich unsichere
   Konfigurationen.
3. **`KC_HOSTNAME`** auf die echte Domain setzen (z.B.
   `KC_HOSTNAME=pflege-finder.example.org`), damit Keycloak in Tokens/
   Redirects nicht `localhost` ausgibt.
4. **Redirect-URIs im Client** (`keycloak/realm-export.json` oder direkt in
   der Admin-Konsole) auf die echte Domain anpassen, `http://localhost:*`
   -Einträge danach entfernen.
5. Den direkten Port 8080 idealerweise ganz von `docker-compose.yml`
   entfernen, sobald der Zugriff über `https://<host>/idp/` (nginx)
   bestätigt funktioniert – dann ist die Admin-Konsole nur noch per
   SSH-Tunnel erreichbar, nicht mehr per lokal gemapptem Port.
6. Zertifikat: läuft automatisch über die gleiche TLS-Terminierung wie die
   App (nginx + Let's Encrypt, siehe README Abschnitt 5) – Keycloak selbst
   muss dafür kein eigenes Zertifikat halten (`KC_PROXY=edge` ist dafür
   bereits gesetzt).

**Optional statt eigenem Realm/Usern:** falls die Hochschule bereits einen
zentralen Identity-Provider hat (z.B. Shibboleth/SAML, Azure AD, oder ein
bestehendes Keycloak), kann `hfh-pflege` stattdessen als **Identity
Broker** konfiguriert werden (Realm → Identity Providers), der die
Hochschul-Anmeldung durchreicht, statt eigene Nutzerkonten zu pflegen. Das
wäre in vielen Fällen die bessere Lösung als eigene Accounts – Rücksprache
mit dem Hochschul-IT-Betrieb empfohlen.

### 1.2 App-seitige Anbindung — ✅ umgesetzt

Realisiert in `app/auth.py` (mit `authlib`) + `app/main.py`:

- OAuth-Client wird registriert, sobald `OIDC_ISSUER`/`OIDC_CLIENT_ID`/
  `OIDC_CLIENT_SECRET` gesetzt sind (`settings.oidc_configured`).
- `GET /auth/login` (Redirect zu Keycloak, mit offener-Redirect-Schutz für
  den `next`-Parameter), `GET /auth/callback` (Token-Tausch, Session-Cookie
  setzen), `GET /auth/logout` (lokales Cookie löschen + Keycloaks
  `end_session_endpoint` aufrufen – vollständiger SSO-Logout, nicht nur
  lokal), `GET /auth/me` (Debug-Status).
- `LoginRequiredMiddleware` schützt `/` und `/api/*`; ausgenommen sind nur
  `/auth/*`, `/static/*`, `/healthz`.
- Session-Zustand liegt in einem signierten, httponly Cookie
  (`SessionMiddleware`, `SECRET_KEY` aus `.env`) – kein serverseitiger
  Session-Store (passt zum zustandslosen Rest der App).
- `ProxyHeadersUvicornWorker` (`app/gunicorn_worker.py`) sorgt dafür, dass
  die App hinter nginx korrekt `https://` statt `http://` in generierten
  Redirect-URIs verwendet (sonst lehnt Keycloak den Callback mit „invalid
  redirect_uri“ ab – dieser Bug ist beim Testen aufgetreten und wurde
  gefixt).
- Fail-Fast: App verweigert den Start, wenn `AUTH_ENABLED=true` ohne
  vollständige OIDC-Konfiguration, oder wenn im Produktivmodus (`ENVIRONMENT=production`)
  der Default-`SECRET_KEY` unverändert ist.

### 1.3 Noch offen für den Produktivbetrieb

- **Rollen/Rechte**: aktuell hat jeder erfolgreiche Login vollen Zugriff.
  Falls nötig, über Keycloak-Realm-Rollen + eine zusätzliche Prüfung in
  `LoginRequiredMiddleware` (Claim im ID-Token) nachrüsten.
- **Produktivhärtung von Keycloak selbst**: siehe 1.1 B (eigene Postgres-DB,
  `start` statt `start-dev`, echter Hostname).
- **Redirect-URIs in `keycloak/realm-export.json`** auf die echte Domain
  anpassen, `localhost`-Einträge danach entfernen (siehe 1.1 B, Punkt 4).
- **Tests**: bisher nur manuell (End-to-End über echte Container) verifiziert,
  kein automatisierter Test für den Login-Flow – siehe Abschnitt 5.

## 2. Von SQLite (In-Memory) zu einer persistenten Datenbank

Sobald es echte Schreibvorgänge gibt (z.B. Pflege der Stellen-Daten über ein
Admin-Interface statt CSV-Import), sollte auf **PostgreSQL** umgestiegen
werden. Da bereits mit SQLAlchemy-Modellen gearbeitet wird, ist das primär
ein Wechsel der Connection-URL + ein zusätzlicher `db`-Service in
`docker-compose.yml` + Alembic für Migrationen.

## 3. Let's Encrypt statt selbstsigniertem Zertifikat

Für den echten Ubuntu-Server-Betrieb: `certbot` (Standalone- oder
Nginx-Plugin-Modus) als zusätzlicher Compose-Service bzw. Cronjob, der
Zertifikate automatisch bezieht und erneuert. Domain + DNS-Eintrag auf den
Server sind Voraussetzung.

## 4. mailto-Limitierung entschärfen

- Warnung im UI ab z.B. 20 ausgewählten Adressen ("könnte vom Mailprogramm
  gekürzt werden").
- Optional: Auswahl in mehrere `mailto:`-Aufrufe/Fenster aufteilen.

## 5. Weitere sinnvolle Ausbaustufen

- Automatisierte Tests (Pytest für die API, ggf. Playwright für die UI).
- CI/CD-Pipeline (z.B. GitHub Actions): Lint + Tests + Docker-Build bei jedem
  Push, Deploy auf den Ubuntu-Server bei Merge nach `main`.
- Strukturiertes Logging + einfaches Monitoring (z.B. Healthcheck-Uptime via
  Uptime Kuma, ebenfalls leicht per Docker Compose zu ergänzen).
- Kartenansicht der Zentren (Geokoordinaten sind bereits im Datensatz
  vorhanden).
- Regelmäßiger Daten-Sync-Job statt manuellem CSV-Import, falls eine
  offizielle/aktuellere Datenquelle angebunden wird.
- Backups: sobald echte Nutzdaten (z.B. Postgres) existieren, Backup-Strategie
  für den Ubuntu-Server festlegen (z.B. `pg_dump` per Cron + Offsite-Kopie).
