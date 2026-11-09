# AP5 – E-Mail-Kommunikationsmodul & Historisierung

Issue #20 · Basis: `main` @ `3531471` (26.10.2026)

## Was AP5 leistet

| Anforderung (Detailanforderungen PL2, „E-Mail-Funktionen“) | Umsetzung |
|---|---|
| Automatische Übernahme der E-Mail-Adressen aus der Datenbank | Der Browser schickt nur Einrichtungs-IDs oder Filter. Der Server liest die Adressen aus `centers.email`. Felder mit mehreren Adressen (`a@x.de; b@x.de`, in den Echtdaten ca. 15 %) werden aufgeteilt. |
| Auswahl einzelner oder mehrerer Empfänger | Checkbox-Auswahl (`center_ids`) oder alle Treffer der aktuellen Filter (Suche, Bundesland, Angebot) – auch über die 200 angezeigten Einträge hinaus. |
| Versand über Mail-Client, als BCC | `mailto:`-Link nur mit `bcc=` (nie `to`/`cc`). Höchstens **20** Adressen pro E-Mail und höchstens **1.800** Zeichen Linklänge; größere Auswahlen werden in Gruppen geteilt. Jede Gruppe öffnet sich nur durch einen eigenen Klick. |
| Historisierung inkl. Anzahl der Empfänger | Tabelle `mail_history`: Zeitpunkt, Betreff, Text, BCC-Adressen, Anzahl, Gruppe *n/m*, Bundesländer, angemeldete Person. |
| Dokumentation versendeter Nachrichten | `GET /api/mail-history` mit Filtern für das AP6-Dashboard. |
| Dimensionen Zeit und Region | `created_at` (Filter Jahr/Monat), `bundeslaender` je Eintrag. |

**Wichtig:** Eine Webanwendung kann bei `mailto:` nicht feststellen, ob die Mail
im Mailprogramm wirklich abgeschickt wurde. Ein Eintrag bedeutet deshalb
„an das Mailprogramm übergeben“ (`status = handoff_attempted`), **nie**
„versendet“. Die Datenbank erzwingt das per CHECK-Regel.

Doppelte Adressen (ohne Groß-/Kleinschreibung) werden nur einmal angeschrieben,
Einrichtungen ohne Adresse werden übersprungen und in der Vorschau gezählt.

## Bedienung (Startseite)

1. Optional unter „E-Mail-Text“ Betreff und Nachricht eintragen (kurz halten).
2. **Checkbox-Auswahl:** Einrichtungen anhaken → „E-Mail an Auswahl senden“.
   Die erste BCC-E-Mail öffnet sich sofort. Bei mehr als 20 Adressen zeigt der
   Button „Nächste BCC-E-Mail öffnen (2/3)“ – jeder Klick öffnet die nächste Gruppe.
3. **Filter-Auswahl:** Filter setzen → „Alle gefilterten Treffer per E-Mail“.
   Es wird zunächst **nur** angezeigt, wie viele Empfänger und E-Mails entstehen;
   geöffnet wird erst mit „Nächste BCC-E-Mail öffnen (1/…)“.
4. „Auswahl leeren“ bricht eine vorbereitete Serie ab.

Die Eingabefelder sind bewusst schlicht und tragen die IDs aus dem AP6-Entwurf
(`email-subject`, `email-body`), damit AP6 Layout und Dashboard übernehmen kann.

## API

Alle Endpunkte liegen unter `/api` und sind damit durch die bestehende
Keycloak-Login-Pflicht geschützt (ohne Login: Umleitung auf `/auth/login`).

### `POST /api/mail/prepare`

```json
{"center_ids": [10, 30], "subject": "Anfrage", "body": "Guten Tag"}
```
oder
```json
{"filters": {"bundesland": "SN", "angebot": "pflegeberatung"}, "subject": "Anfrage"}
```

Antwort: `campaign_id`, Zähler (`selected_centers`, `reached_centers`,
`centers_without_email`, `centers_without_valid_email`, `invalid_addresses`,
`duplicate_emails`, `recipient_count`, `batch_count`) und je Gruppe
`number`, `recipient_count`, `bundeslaender`, `handoff_token`.
**Schreibt noch keine Historie.** Unbekannte Felder (z. B. eigene
E-Mail-Adressen) werden mit 422 abgelehnt.

Das `handoff_token` ist mit `SECRET_KEY` signiert, 1 Stunde gültig und enthält
die Adressen, Betreff und Text als unveränderbare Momentaufnahme. Es ist
signiert, aber **nicht verschlüsselt** – nicht in Logs oder URLs ablegen.

### `POST /api/mail/handoff`

```json
{"handoff_token": "<aus /prepare>"}
```

Prüft Signatur und Alter, schreibt einen Historieneintrag und liefert
`history` und `mailto_url`. Derselbe Token erzeugt auch bei Wiederholung nur
**einen** Eintrag.

### `GET /api/mail-history`

Parameter: `limit` (1–200, Standard 50), `offset`, `year`, `month` (nur mit
`year`, Grenzen in UTC), `search` (Betreff/Text), `campaign_id`. Neueste zuerst.

## Konfiguration (optional, `.env`)

| Variable | Standard | Bedeutung |
|---|---|---|
| `MAIL_BCC_BATCH_SIZE` | `20` | Adressen pro E-Mail (1–20) |
| `MAIL_MAX_MAILTO_LENGTH` | `1800` | maximale Länge eines `mailto:`-Links |

## Datenbank und Migration

AP5 nutzt die vorhandene PostgreSQL-Datenbank `app-db` – keine zweite
Datenbank, kein neues Volume, keine Änderung an `centers`, `services`,
`center_services`.

- **Neue (leere) Volumes:** `db/init/002_create_mail_history.sql` legt die Tabelle an.
- **Bestehende Datenbank (Server):** Docker führt `db/init/` dort nicht erneut
  aus. Deshalb legt die App beim Start **nur diese eine Tabelle** an, falls sie
  fehlt (`ensure_mail_history_table` in `app/mail_models.py`). Eine
  PostgreSQL-Sperre (`pg_advisory_xact_lock`) verhindert, dass die zwei
  Gunicorn-Worker sie gleichzeitig anlegen – ohne Sperre stürzten im Test bis zu
  7 von 8 gleichzeitig startenden Prozessen ab.
- Existiert eine Tabelle `mail_history` mit veraltetem Schema, startet die App
  mit klarer Fehlermeldung nicht (gleiches Fail-fast-Prinzip wie bei fehlenden
  Pflicht-Tabellen).
- Voraussetzung: Das App-Konto darf im Schema `public` Tabellen anlegen. Mit
  der Compose-Konfiguration (`POSTGRES_USER=pl2` ist Eigentümer) ist das erfüllt.
- **Keine Volumes löschen, keine Datenbank zurücksetzen.** Vor dem ersten
  Produktiv-Deploy ist ein Backup sinnvoll (unabhängig von AP5):
  `docker compose exec -T app-db pg_dump -U pl2 pflegedb > backup.sql`

Zurückrollen (nur nach Teamabsprache): Code-Rollback genügt; die Tabelle stört
die alte Version nicht. Entfernen nur bewusst mit `DROP TABLE mail_history;`.

## Datenschutz (vom Team zu entscheiden)

Die Historie speichert E-Mail-Adressen (teils personenbezogen, z. B.
`vorname.nachname@…`), Nachrichtentexte und die angemeldete Person.

- **Zugriff:** Derzeit dürfen alle angemeldeten Nutzer:innen die Historie lesen
  (das Projekt hat noch keine Rollen, siehe ROADMAP).
- **Aufbewahrung:** Es gibt noch keine automatische Löschung. Eine Frist (z. B.
  12 Monate) sollte im Team bzw. mit den Projektverantwortlichen festgelegt werden.
- Mail-Inhalte sollten keine sensiblen Daten über Pflegebedürftige enthalten.

## Tests

```sh
ruff check .
pytest -q                     # inkl. tests/test_mail.py (SQLite wie alle Projekttests)
node --check app/static/js/app.js
```

Zusätzlich gegen ein **echtes PostgreSQL** (nur Wegwerf-Testdatenbank, deren
Name „test“ enthält; die Tests arbeiten in einem temporären Schema):

```sh
AP5_TEST_POSTGRES_URL=postgresql+psycopg://pl2:PASSWORT@localhost:5432/pflegedb_test pytest -q tests/test_mail_postgres.py
```

Geprüft werden u. a.: gleichzeitiger Start mehrerer Worker, identisches Schema
aus SQL-Datei und App-Start, bestehende Team-Datenbank bleibt unverändert,
Persistenz über einen Neustart, Datenbankregeln (max. 20, Status nie `sent`).

## Offene Punkte

- Manuell mit echten Mailprogrammen (Outlook, Thunderbird, Apple Mail) und
  **Test-Adressen** prüfen: öffnet sich das Programm, stehen alle Adressen im BCC?
- Rollen/Rechte und Aufbewahrungsfrist für die Historie (Team/Datenschutz).
- Dashboard-Ansicht der Historie in AP6 (API ist bereit).
- Sehr große Filter (z. B. ganz Deutschland, ~4.200 Adressen) ergeben über 200
  einzelne E-Mails; das ist technisch korrekt, fachlich aber selten sinnvoll.
