<!--
# Autor: Gabriel Pfuner (github.com/3mg4, Matrikelnummer: 1142226)
Dieses Dokument ist die technische Bewertung zu Issue #29: verglichene Optionen
zur Datenabbildung und -verwaltung (Bewertungsmatrix), die Schema-Entscheidung,
der Weg dorthin (Initialisierung + ETL-Import) sowie Betrieb und Grenzen.
-->

# Technische Bewertung: Datenabbildung und Verwaltung der Projektdaten in einer Datenbank

**Autor:** Gabriel Pfuner

**Projekt:** PL2-HFH – Pflegezentren-Finder ([github.com/mbrx387/PL2-HFH](https://github.com/mbrx387/PL2-HFH))
**Bezug:** Issue #29 „Technische Bewertung“
**Stand:** November 2026 · **Datenbestand:** 4.092 Pflege- und Beratungsstellen (`app/data/pflegestellen.csv`)

Dieses Dokument bewertet die technischen Möglichkeiten, die gesammelten Daten
(Pflege- und Beratungsstellen mit Kontaktdaten, Leistungen und Geokoordinaten)
abzubilden und in einer Datenbank zu verwalten. Es erläutert die Entscheidung für
den gewählten Weg, den Weg dorthin und stellt die Datenbank auch für die Zukunft
nachvollziehbar und transparent dar. Alle Aussagen beziehen sich auf den
tatsächlichen Umsetzungsstand im Repository.

---

## 1. Ausgangslage und Anforderungen

Der Datenbestand stammt aus einer kuratierten CSV-Datei (`app/data/pflegestellen.csv`,
4.092 Einträge, versioniert im Git). Erzeugt und validiert wird sie durch die
separate ETL-Pipeline `GetDataFromAPI/` (GitHub-Action-Workflow
`.github/workflows/GetDataFromAPI.yml`: Fetch, Validierung, Transformation,
atomares Publizieren als CSV-Artefakt). Auf dem Server holt
`scripts/fetch_latest_getdatafromapi_artifact.py` die neueste CSV nach
`db/temp/pflegestellen.csv`, und ein wöchentlicher Cron-Job
(`scripts/setup_import_cron.sh` -> `scripts/import_latest_centers.sh`) spielt sie
in die produktive Datenbank ein. Daraus ergeben sich folgende Anforderungen an
die Datenhaltung:

| Nr. | Anforderung | Begründung |
| --- | --- | --- |
| A1 | **Persistenz über Container-Neustarts hinaus** | Produktivbetrieb: Verlust der Verzeichnisdaten wäre ein Ausfall der Anwendung. Umsetzung: benanntes Docker-Volume `app-db-data`. |
| A2 | **Gemeinsame Datenquelle für App und Import** | Web-App (Lese-/Schreibzugriff via Datenpflege) und Cron-Import arbeiten auf denselben Daten; Insellösungen führen zu divergierenden Ständen. |
| A3 | **Konsistenz bei nebenläufigen Zugriffen** | 2 Gunicorn-Worker (`app/Dockerfile`) + wöchentlicher Import-Job + Datenpflege greifen gleichzeitig zu; Zwischenzustände dürfen nie sichtbar werden. |
| A4 | **Strukturierte, serverseitig abfragbare Daten** | Suche (Freitext, Bundesland, Angebot) läuft in `app/routers/centers.py` (`apply_center_filters`) als SQL, nicht im Browser; Paginierung max. 500 (`MAX_PAGE_SIZE`). |
| A5 | **Sicherheit und Datenschutz** | Institutionelle Kontaktdaten, öffentlich über nginx erreichbar: DB-Dienst ohne Host-Ports, Zugangsdaten nur aus `.env` (Fail-fast in `docker-compose.yml`). |
| A6 | **Betreibbarkeit durch ein kleines, wechselndes Team** | Hochschulprojekt: kein dedizierter DBA. Lernkurve und Wartungsaufwand sind harte Bewertungskriterien. |
| A7 | **Backup/Restore und Wiederherstellbarkeit** | `scripts/backup_db.sh`: `pg_dump -Fc -Z 9` beider Datenbanken, Verifikation via `pg_restore --list`, 14 Tage Rotation, `chmod 600`. |
| A8 | **Erweiterbarkeit** | Rollen `read_centers`/`write_centers` über Keycloak, Leistungen als eigener Katalog (`services`), Querschnittstabelle `mail_history` (AP5). |

---

## 2. Bewertete Optionen

Bewertungskriterien (Skala 1 = schlecht bis 5 = sehr gut): Eignung Datenmodell,
Konsistenz/Transaktionen, Nebenläufigkeit, Betrieb/Komplexität, Ökosystem/Lernkurve,
Sicherheit/Datenschutz, Backup/Restore und Erweiterbarkeit.

### Option A: CSV/Flat Files (kein DBMS)

Die App liest `app/data/pflegestellen.csv` direkt bei jedem Request.

- Vorteile: keine zusätzliche Infrastruktur, versionierbar im Git.
- Nachteile: keine Transaktionen und kein nebenläufiger Schreibzugriff (die Datenpflege-UI würde Datei-Lösch- und Überschneidungsprobleme erzeugen); Suche/Filter müssten bei jedem Request alle 4.092 Zeilen im Python-Code parsen; keine Integritätsprüfung (PLZ, Koordinaten, Dubletten); Anforderungen A2, A3, A4, A8 vollständig verfehlt.

**Bewertung:** Ausscheidet. Für einen schreibenden Mehrbenutzerbetrieb ungeeignet.

### Option B: SQLite (dateibasiertes RDBMS im Container-Volume)

- Vorteile: wird von der Code-Basis bereits unterstützt (`app/database.py` erkennt SQLite-URLs; Tests laufen mit SQLite, bei `:memory:` mit `StaticPool`), kein eigener Dienst, ACID-Transaktionen vorhanden.
- Nachteile: schreibende Nebenläufigkeit schwach (eine Schreib-Transaktion sperrt die ganze Datei; der wöchentliche Import würde die App blockieren); kein eigener Dienst mit getrennten Credentials im Compose-Netz; Backup/Healthcheck nur über das Dateisystem, kein `pg_dump`-komfortables Restore.

**Bewertung:** Sehr gut für lokale Entwicklung und Tests (wird dort auch genutzt), aber nicht als Produktionsspeicher.

### Option C: MongoDB (Dokumentendatenbank)

Ein JSON-Dokument pro Center inkl. eingebetteter Leistungen.

- Vorteile: schema-flexibel, entspräche direkt der CSV-Zeilen-Struktur.
- Nachteile: Schema-Freiheit ist hier ein Nachteil – die Daten sind tatsächlich relational (eine Leistungsart gehört zu vielen Stellen, n:m), und die Datenpflege braucht validierte, typisierte Felder (Pydantic/SQLAlchemy-Modelle existieren bereits); zweites Abfrage-Ökosystem neben SQLAlchemy, höherer Lernaufwand; transaktionale Konsistenz und der bewährte ETL-Upsert (`ON CONFLICT`) weniger direkt abbildbar.

**Bewertung:** Für ein relationslastiges Verzeichnis mit klarer Struktur und bestehendem ORM-Pfad kein Vorteil, dafür mehr Betriebs-/Lernrisiko.

### Option D: MySQL / MariaDB

- Vorteile: vollwertiges RDBMS, weit verbreitet, gut mit Docker Compose betreibbar.
- Nachteile: funktionell eng an PostgreSQL heran, aber im Python-/FastAPI-/SQLAlchemy-Kontext ist PostgreSQL heute der De-facto-Standard (`psycopg` 3 ist in `app/requirements.txt` fixiert); Community-Ressourcen und Beispiele häufen sich dort; weniger komfortable Constraint- und Upsert-Details für dieses Schema.

**Bewertung:** Solide Alternative ohne konkreten Vorteil gegenüber E bei gleichen Betriebskosten.

### Option E (gewählt): PostgreSQL 16 über SQLAlchemy, initialisiert aus `db/init/`, befüllt per ETL-CSV-Import

Umgesetzt als Compose-Dienst `app-db` (`postgres:16-alpine`), angebunden über SQLAlchemy 2.x mit `psycopg` 3 (`app/database.py`, `app/models.py`).

- Vorteile: vollwertiges ACID-RDBMS; transaktionaler, idempotenter Import (`db/import_centers.sql`); nebenläufige Nutzung durch 2 Gunicorn-Worker, Datenpflege und Cron-Import zuverlässig möglich.
- Vorteile: `ON CONFLICT DO UPDATE`-Upserts machen den Import wiederholbar ohne Zwischenzustände.
- Vorteile: SQLAlchemy-ORM liefert Python-typisierte Modelle, die mit den Pydantic-API-Schemas korrespondieren (`app/schemas.py`); DB-seitige CHECK-Constraints (PLZ `^[0-9]{5}$`, Koordinaten in der Deutschland-Bounding-Box 47–56 / 5–16) sichern Integrität zusätzlich zur Anwendungsvalidierung.
- Vorteile: offizielles schlankes Image, Healthcheck via `pg_isready`, Backup-Komfort via `pg_dump -Fc`.
- Vorteile: läuft nur im internen Compose-Netzwerk `internal` (kein `ports`-Mapping) – erfüllt A5.

### Bewertungsmatrix

| Kriterium | A: CSV | B: SQLite | C: MongoDB | D: MySQL | **E: PostgreSQL (SQLAlchemy)** |
| --- | --- | --- | --- | --- | --- |
| Eignung Datenmodell (relational, n:m) | 1 | 4 | 2 | 4 | **5** |
| Konsistenz / Transaktionen | 1 | 4 | 3 | 4 | **5** |
| Nebenläufigkeit (Worker + Cron + Datenpflege) | 1 | 2 | 4 | 4 | **5** |
| Betrieb / Komplexität (kleines Team) | 5 | 5 | 3 | 4 | **4** |
| Ökosystem / Team-Lernkurve (FastAPI, psycopg, Pydantic) | 4 | 5 | 3 | 4 | **5** |
| Sicherheit / Datenschutz (internes Netz, eigene Credentials) | 2 | 3 | 3 | 4 | **5** |
| Backup / Restore / Erweiterbarkeit | 1 | 3 | 4 | 4 | **5** |
| **Summe** | **15** | **26** | **22** | **28** | **34** |

---

## 3. Entscheidung für den Weg innerhalb von PostgreSQL: das normalisierte Schema

Die zweite Bewertungsfrage war nicht nur *welches* DBMS, sondern *wie* die Daten
abgebildet werden. Drei Gestaltungen standen im Raum:

### Variante 1: Breite Tabelle (eine Spalte pro Leistungsart)

Die CSV-Spalten (`pflegestuetzpunkt`, `pflegeberatung`, `wohnberatung`, …) würden
als boolesche Spalten in einer großen `centers`-Tabelle fortgeführt.

- Voruteil: sehr einfach, keine Joins.
- Nachteil: bei jeder neuen Leistungsart ist ein Schema-Eingriff (`ALTER TABLE`) nötig; die Filter-API müsste je Spalte spezialisiert werden.

### Variante 2: JSON/JSONB-Spalte für Leistungen

- Vorteil: maximale Flexibilität ohne Schema-Änderung.
- Nachteil: verliert die referenzielle Verwaltung der Leistungen (Tippfehler erzeugen Duplikate wie „Pflegeberatung“ vs. „Pflege -Beratung“), keine Foreign Keys, Filter nicht normalisierbar.

### Variante 3 (gewählt): Normalisiertes Schema mit n:m-Zuordnungstabelle

Drei Tabellen mit referenzieller Integrität, umgesetzt in `db/init/001_create_centers.sql`
und gespiegelt in den ORM-Modellen `app/models.py` (zusätzlich `mail_history` aus
`db/init/002_create_mail_history.sql` für die AP5-E-Mail-Historie):

```mermaid
erDiagram
  CENTERS ||--o{ CENTER_SERVICES : "bietet"
  SERVICES ||--o{ CENTER_SERVICES : "wird angeboten in"
  CENTERS {
    int id PK "stabile unsere_id aus der Quelle"
    varchar zqp_id UK "externer Schluessel"
    text name
    char bundesland "ISO-Code, 2-stellig"
    char plz "CHECK ^[0-9]{5}$"
    text ort
    text adresse
    text email
    text telefon
    text website
    double latitude "CHECK 47..56"
    double longitude "CHECK 5..16"
    bool aktiv "Soft-Delete statt Loeschen"
    bool manuell_gepflegt "Sperrvermerk gegen Import (Issue #85)"
    varchar manuell_geaendert_von
    timestamptz manuell_geaendert_am
    timestamp quelle_updated_at
    timestamptz created_at
    timestamptz updated_at
  }
  SERVICES {
    int id PK "IDENTITY"
    text name UK
    text beschreibung
  }
  CENTER_SERVICES {
    int center_id PK FK
    int service_id PK FK
  }
```

**Warum die normalisierte Variante gewonnen hat:**

1. **Das Domänenmodell ist eindeutig n:m.** Eine Leistungsart gehört zu vielen Stellen, eine Stelle bietet viele Leistungen – direkt im Schema abgebildet.
2. **Integrität per FK und `ON DELETE CASCADE`.** Beim Re-Import werden Zuordnungen gelöscht und neu aufgebaut, ohne verwaiste Zeilen.
3. **Selbstbeschreibende Filter-API.** Der Angebotsfilter ist ein Join auf den kanonisierten `services.name` (`Center.services.any(Service.name == ...)` in `app/routers/centers.py`), keine hartkodierte boolesche Enumeration.
4. **Neue Leistungsarten sind Datensätze, keine Migration.** Der Import erkennt neue Leistungen über das CSV selbst (`INSERT ... ON CONFLICT (name) DO NOTHING` in `services`) – das Schema bleibt stabil.
5. **Abwärtskompatibilität als berechnete Properties.** Die booleschen Felder des CSV-Formats bleiben als Properties an `Center` (`pflegestuetzpunkt`, `pflegeberatung`, … in `app/models.py`) und in den `CenterOut`-Pydantic-Schemas erhalten – Bestandteil der API und UI, ohne das physische Schema zu verschmutzen.

---

## 4. Der Weg dorthin: Initialisierung und ETL-Import

Der Import ist der Transparenz- und Wiederholbarkeitsanspruch, umgesetzt in Code:

1. **Versionierter Rohdatensatz:** `app/data/pflegestellen.csv` liegt im Repository; jede Änderung ist in der Git-Historie sichtbar. Die produktive Quelle ist die vom GetDataFromAPI-Workflow publizierte CSV, die der Server nach `db/temp/pflegestellen.csv` holt.
2. **Schema-Initialisierung:** `db/init/001_create_centers.sql`, `002_create_mail_history.sql` und `003_manual_maintenance.sql` laufen beim ersten Start eines leeren Volumes automatisch über `docker-entrypoint-initdb.d` (read-only gemountet). Für bestehende Datenbanken legt `app/maintenance.py` (`ensure_manual_maintenance_columns`, mit Advisory Lock gegen parallel startende Gunicorn-Worker) dieselben Spalten idempotent beim App-Start an.
3. **Eine Transaktion für alles:** `scripts/import_latest_centers.sh` ruft `psql -v ON_ERROR_STOP=1` mit `db/import_centers.sql` auf; der Import läuft in `BEGIN` … `COMMIT` und bricht bei Fehlern als Ganzes ab (Rollback). Halbfertige Imports sind ausgeschlossen.
4. **Temporäre Staging-Tabelle:** `CREATE TEMP TABLE centers_import … ON COMMIT DROP` – die CSV (`\copy`, Delimiter `;`) wird gelesen und transformiert (`btrim`, `NULLIF`, explizite Casts), ohne die produktiven Tabellen zu berühren.
5. **Schutz manueller Daten (Issue #85):** Ein Guard bricht den Import ab, wenn eine `unsere_id >= 1.000.000` (manueller ID-Bereich) in der CSV auftaucht; ein Sperrfilter entfernt Import-Zeilen, die einen `manuell_gepflegt`-Eintrag matchen (über `id`, `zqp_id` oder den Lokal-Schlüssel name|adresse|plz|ort) – die Anzahl landet per `NOTICE` im Import-Log.
6. **Idempotenter Upsert:** `unsere_id` aus der Quelle wird als stabiler Primärschlüssel (`centers.id`) übernommen; `ON CONFLICT (id) DO UPDATE` aktualisiert bestehende Einträge statt zu duplizieren. Eine `zqp_id`-Kollision mit einem nicht gesperrten Eintrag wird vorab auf die bestehende ID umgebogen.
7. **Neuaufbau der Zuordnungen:** `DELETE` der betroffenen `center_services`, danach Reinsert aus dem kanonischen `services`-Katalog – aus der Quelle entfernte Leistungen werden sauber zurückgenommen.
8. **Reproduzierbarkeit:** flock gegen Doppelläufe (`LOCK_FILE`), sha256-Marker (`db/temp/.last_imported`) gegen erneutes Einspielen derselben CSV, `pg_isready`-Check vor dem Import. Der Vorgang kann beliebig oft laufen, ohne Zustandsverschlechterung.

Die Web-App selbst liest dieselben Tabellen (`GET /api/centers` in `app/routers/centers.py`), lädt keine Dateien beim Start und überschreibt nichts – eine einzige, gemeinsam genutzte Quelle der Wahrheit. Schreibzugriffe (Anlegen/Ändern/Deaktivieren) sind rollen-geschützt (`write_centers`), vergeben manuelle IDs ab 1.000.000 (`MANUAL_ID_START`), setzen den Sperrvermerk und löschen weich (`aktiv = false`).

---

## 5. Betrieb und technische Detailentscheidungen

| Aspekt | Umsetzung | Nachvollziehbarkeit |
| --- | --- | --- |
| Container-Isolation | `app-db` nur im internen Compose-Netzwerk `internal` (kein `ports`, Volume `app-db-data`); eigener DB-User `pl2` / DB `pflegedb`; Passwort nur aus `.env` (`${APP_DB_PASSWORD:?set-in-.env}` Fail-fast) | `docker-compose.yml`, kommentiert |
| App-Härtung | `app` nur per `expose 8000` intern, `read_only: true` + tmpfs, 2 Gunicorn-Worker mit Proxy-Headers-Worker, Ressourcen-Limits 1 CPU / 512 MB; nginx terminiert TLS und ist der einzige öffentliche Port (80/443) | `docker-compose.yml`, `app/Dockerfile`, `nginx/` |
| Schema-Quelle | Init-Skripte `db/init/` + SQLAlchemy-Modelle (`app/models.py`); danach ETL als Datenquelle | Schema ist im Code nachlesbar, nicht nur in der DB |
| Pooling/Resilienz | `pool_pre_ping=True` für das Produktiv-Backend (bei SQLite/dev bewusst andere Engine-Optionen) | `app/database.py` |
| Validierung | Pydantic (`app/schemas.py`): PLZ `^\d{5}$`, Bundesland 2-stellig + Normalisierung, Lat/Long 47–56 / 5–16, Website http(s); zusätzlich DB-CHECK-Constraints auf `plz`, `latitude`, `longitude` | `app/schemas.py`, `db/init/001_create_centers.sql` |
| Backup | `scripts/backup_db.sh`: `pg_dump -Fc -Z 9` für `pflegedb` UND `keycloak`, Verifikation via `pg_restore --list`, flock, 14-Tage-Rotation, `chmod 600`, Backup-dir `/var/backups/pl2-hfh` | `scripts/backup_db.sh`, `docs/ImportSkript.md` |
| Trennung SSO-Daten | Keycloak erhält eine getrennte PostgreSQL-Instanz (`keycloak-db`, Profil `sso`) – Verzeichnisdaten und Identity-Daten sind fachlich getrennt und separat backup-bar | `docker-compose.yml` |
| Tests | Unit-/API-Tests mit SQLite (`app/database.py`), E2E mit Playwright gegen eigene Test-DB per Docker | `tests/`, `e2e/` |

---

## 6. Entscheidung, transparent zusammengefasst

> **Entscheidung:** Die Projektdaten werden in einem **PostgreSQL 16** (Dienst `app-db`, Datenbank `pflegedb`) in einem **normalisierten Drei-Tabellen-Schema** (`centers` / `services` / `center_services`, referenziell per n:m-Zuordnungstabelle verbunden, ergänzt um `mail_history`) persistiert. Die Anbindung erfolgt über **SQLAlchemy 2 mit psycopg 3**; befüllt wird die DB durch den **transaktionalen, idempotenten ETL-Import** (`db/import_centers.sql` via `scripts/import_latest_centers.sh`, wöchentlich per Cron) und – rollen-geschützt mit Sperrvermerk – über die Datenpflege der App.
>
> **Begründung in einem Satz:** Unter den bewerteten Optionen ist dies die einzige, die nebenläufige, schreibende Nutzung durch App-Worker, Datenpflege und Import bei voller transaktionaler Konsistenz, referenzieller Integrität (FK, CHECK, UNIQUE) und ohne Schema-Eingriffe bei neuen Leistungsarten bietet und trotzdem mit einem einzigen Compose-Service, ohne öffentlichen DB-Port und ohne dedizierten DBA betreibbar ist.
>
> **Bewusst nicht gewählt:** Flat-Files/CSV (keine nebenläufige Verwaltung), SQLite als Produktionsspeicher (Schreib-Sperren, kein Dienst), MongoDB (kein Modellvorteil, höherer Lernaufwand), MySQL (gleichwertig, aber ohne Ökosystem-Vorteil im FastAPI/SQLAlchemy-Stack).

## 7. Grenzen und weiterer Weg (damit die Entscheidung auch zukünftig prüfbar bleibt)

Damit zukünftige Entscheidungen (z. B. zentraler Daten-Sync, Historisierung, echte PostGIS-Kartenansicht) an denselben Kriterien gemessen werden können, sind die heutigen Grenzen bewusst dokumentiert:

1. **Quelle vs. Datenpflege:** Die CSV/ETL-Quelle bleibt Single-Source-of-Truth für den Dateninhalt; manuell gepflegte Einträge sind durch den Sperrvermerk (`manuell_gepflegt`, Issue #85) geschützt und werden weder überschrieben noch dupliziert. Beim geplanten Daten-Sync aus einer offiziellen Quelle ist zu entscheiden, ob Quelle oder App-Datenpflege Vorrang hat.
2. **Keine Historisierung (kein SCD).** `updated_at` und `quelle_updated_at` dokumentieren den Stand eines Datensatzes, frühere Zustände sind nicht rekonstruierbar. Für die Einrichtungspflege ausreichend; Historisierung wäre bei Berichtsanforderungen nachzurüsten.
3. **Import validiert Struktur, nicht Semantik.** CHECK-Constraints und `ON_ERROR_STOP` sichern Format und Integrität (PLZ, Koordinaten, Dubletten über UNIQUE), semantisch falsche Datensätze (Tippfehler in E-Mails, falsche Aber plausible PLZ) erkennt der Import nicht – dafür ist die Validierung in `GetDataFromAPI` (PR-validate-Job) und Pydantic zuständig.
4. **Filter und Suche laufen serverseitig über Standard-SQL.** Soll die Datenmenge oder Suchlogik signifikant wachsen (Volltextsuche), ist `pg_trgm`/`GIN`/`tsvector` in PostgreSQL ohne Systemwechsel nachrüstbar – ein weiterer Grund für Option E.
