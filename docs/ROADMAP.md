# Roadmap

Stand: Oktober 2026 · Anwendung läuft produktiv unter `https://projekthfh.tech`
(Login und automatisches Deployment funktionieren).

Betriebsanleitung (Server-Inbetriebnahme, Keycloak): siehe
[README, Abschnitt 8](../README.md#8-server-inbetriebnahme).

---

## ✅ Umgesetzt

**Anwendung**
- FastAPI-Webanwendung: Liste von ~4.090 Pflege-/Beratungsstellen mit Suche,
  Filtern (Bundesland, Angebot) und Mehrfachauswahl
- Sammel-E-Mail über das eigene Mailprogramm (`mailto:`), kein Mailversand
  durch den Server
- In-Memory-SQLite, beim Start aus versionierter CSV befüllt; stabile IDs
- API mit Eingabevalidierung und Begrenzung der Ergebnisgröße

**Login / SSO**
- Login-Pflicht über Keycloak (OpenID Connect), inkl. vollständigem SSO-Logout
- Signiertes Session-Cookie, kein serverseitiger Session-Speicher
- Fail-fast: App startet nicht bei fehlender OIDC-Konfiguration oder
  schwachem/Platzhalter-`SECRET_KEY`

**Keycloak-Betrieb**
- Produktivmodus mit eigener Postgres-Datenbank (persistentes Volume)
- Hostname und Redirect-URIs aus `.env`, automatischer Realm-Import
- Admin-Konsole nur per SSH-Tunnel erreichbar (öffentlich gesperrt)

**Infrastruktur & Sicherheit**
- Docker Compose: App, nginx, Keycloak, Postgres in internem Netzwerk
- nginx als TLS-Reverse-Proxy mit Rate-Limiting
- Security-Header (CSP u. a.), Container als Non-Root mit Read-only-Dateisystem
  und Ressourcenlimits

**CI/CD & Qualität**
- GitHub Actions: Lint + Tests → Image-Build (GHCR, Commit-SHA-Tag) →
  Deploy per SSH → Health-Check
- Vorab-Prüfung der Server-`.env` und Zertifikate mit klaren Fehlermeldungen
- 17 automatisierte Tests (Pytest), Linting (ruff)
- Dependabot + Dependency Graph für alle Abhängigkeiten
- Gitleaks-Pre-Commit-Hook gegen versehentlich eingecheckte Secrets

**Dokumentation**
- README (Architektur, Sicherheitskonzept, Betrieb)
- Einsteiger-Erklärung `docs/erklaerung.html`

---

## 🔜 Als Nächstes

### Vor dem offiziellen Go-Live
- [ ] TLS-Zertifikat automatisieren (Let's Encrypt / certbot)
- [ ] Demo-User entfernen, echte Nutzer- und persönliche Admin-Konten anlegen
- [ ] Logout-Redirect-URI im Realm-Import korrigieren (aktuell manuell gesetzt)
- [ ] Impressum und Datenschutzerklärung (ohne Login erreichbar)
- [ ] Keycloak absichern: Brute-Force-Schutz aktivieren, „Passwort vergessen“
      nur mit eingerichtetem E-Mail-Versand
- [ ] Backup der Keycloak-Datenbank

### Backend
- [ ] Login-Prüfung von Middleware auf FastAPI-Dependency umstellen
- [ ] Rollen/Rechte (aktuell hat jeder eingeloggte Account vollen Zugriff)
- [ ] Session an Token-Ablauf in Keycloak koppeln
- [ ] Debug-Endpunkt `/auth/me` nur in der Entwicklung bereitstellen
- [ ] CSV beim Import validieren (fehlerhafte Zeilen melden statt still übernehmen)
- [ ] Tests erweitern (Login-Callback, Logout, Datenimport)

### Betrieb / CI
- [ ] Automatischer Rollback bei fehlgeschlagenem Health-Check
- [ ] GitHub Actions aktualisieren (Node-20-Deprecation) und auf Commit-SHAs pinnen
- [ ] Strukturiertes Logging und Uptime-Monitoring

### Später / optional
- [ ] Persistente Datenbank (Postgres) für die App, sobald Daten im System
      bearbeitet werden sollen
- [ ] Automatischer Daten-Sync aus einer offiziellen Quelle statt CSV-Pflege
- [ ] Warnung/Aufteilung bei sehr vielen E-Mail-Empfängern (`mailto:`-Längenlimit)
- [ ] Kartenansicht (Geokoordinaten sind vorhanden)
- [ ] UI-Tests (Playwright)
- [ ] Anbindung an einen zentralen Hochschul-Login (Keycloak als Identity Broker)
