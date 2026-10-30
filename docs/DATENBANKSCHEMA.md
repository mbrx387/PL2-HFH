# PostgreSQL-Datenbankschema

Diese Dokumentation beschreibt die PostgreSQL-Verbindung der App, das Init-Skript
[`db/init/001_create_centers.sql`](../db/init/001_create_centers.sql), die
Tabellen des Pflegestellenverzeichnisses und den CSV-Import.

## Zweck des Init-Skripts

`001_create_centers.sql` erstellt drei Tabellen:

- `centers` für die Stammdaten der Pflegestellen
- `services` als zentralen Katalog der angebotenen Leistungen
- `center_services` als Zuordnung zwischen Pflegestellen und Leistungen

Außerdem legt das Skript einen Index für Suchen nach `service_id` an und fügt
sechs Standard-Leistungen in `services` ein. Pflegestellen werden anschließend
separat aus einer CSV-Datei importiert.

Das PostgreSQL-Docker-Image führt SQL-Dateien aus
`/docker-entrypoint-initdb.d` automatisch nur aus, wenn das Datenbank-Volume
zum ersten Mal mit einer leeren Datenbank initialisiert wird. Beim Start prüft die App die Verbindung und erwartet alle drei Tabellen.
Sie legt das Schema aber nicht selbst an und importiert keine CSV-Datei
automatisch. Einzige Ausnahme ist die AP5-Tabelle `mail_history` (siehe
unten): Fehlt sie, legt die App nur diese eine Tabelle beim Start an.

## Tabellen

### `centers`

Eine Zeile entspricht einer Pflegestelle. `id` ist die stabile, interne ID;
`zqp_id` dient als eindeutiger externer Schlüssel.

| Spalte | Typ | Bedeutung und Regeln |
|---|---|---|
| `id` | `integer` | Primärschlüssel; stabile ID aus der Datenquelle |
| `zqp_id` | `varchar(32)` | Externe ID; eindeutig, darf fehlen |
| `name` | `text` | Name; erforderlich, Standardwert ist leer |
| `bundesland` | `char(2)` | Zweistelliger Bundesland-/Ländercode; Standardwert ist leer |
| `plz` | `char(5)` | Postleitzahl; leer oder genau fünf Ziffern |
| `ort` | `text` | Ort; Standardwert ist leer |
| `adresse` | `text` | Adresse; Standardwert ist leer |
| `email` | `text` | E-Mail-Adresse; Standardwert ist leer |
| `telefon` | `text` | Telefonnummer als Text, damit Formatierungen erhalten bleiben |
| `website` | `text` | Website; Standardwert ist leer |
| `latitude` | `double precision` | Breitengrad; optional, falls gesetzt zwischen 47 und 56 |
| `longitude` | `double precision` | Längengrad; optional, falls gesetzt zwischen 5 und 16 |
| `aktiv` | `boolean` | Aktiv-Status; standardmäßig `true` |
| `quelle_updated_at` | `timestamp` | Änderungszeitpunkt in der Quelldatei |
| `created_at` | `timestamptz` | Zeitpunkt der Anlage; standardmäßig aktuelle Zeit |
| `updated_at` | `timestamptz` | Zeitpunkt der Änderung; standardmäßig aktuelle Zeit |

### `services`

Der Leistungskatalog verhindert, dass dieselbe Leistung für jede Pflegestelle
erneut als Freitext gespeichert werden muss.

| Spalte | Typ | Bedeutung und Regeln |
|---|---|---|
| `id` | Identity-`integer` | Automatisch erzeugter Primärschlüssel |
| `name` | `text` | Name der Leistung; erforderlich und eindeutig |
| `beschreibung` | `text` | Beschreibung; standardmäßig leer |

Das Init-Skript stellt diese Leistungen bereit: Pflegestützpunkt,
Pflegeberatung, Wohnberatung, Demenzberatung, Angehörigenberatung und
Betreuungsberatung.

### `center_services`

Diese Zuordnungstabelle bildet die n:m-Beziehung ab: Eine Pflegestelle kann
mehrere Leistungen anbieten und eine Leistung kann zu vielen Pflegestellen
gehören.

| Spalte | Typ | Bedeutung und Regeln |
|---|---|---|
| `center_id` | `integer` | Fremdschlüssel auf `centers.id` |
| `service_id` | `integer` | Fremdschlüssel auf `services.id` |

Beide Spalten sind erforderlich. Zusammen bilden sie den Primärschlüssel,
sodass dieselbe Leistung nicht doppelt derselben Pflegestelle zugeordnet
werden kann. Werden eine Pflegestelle oder eine Leistung gelöscht, entfernt
`ON DELETE CASCADE` auch die betroffenen Zuordnungen.

Der Primärschlüssel `(center_id, service_id)` unterstützt insbesondere
Abfragen nach `center_id`. Der zusätzliche Index
`idx_center_services_service_id` unterstützt Abfragen nach `service_id`, etwa
die Suche nach allen Pflegestellen, die eine bestimmte Leistung anbieten.

### `mail_history` (AP5)

Eine Zeile entspricht einer BCC-E-Mail, die die App an das lokale
Mailprogramm übergeben hat. Ob die Mail dort abgeschickt wurde, ist bei
`mailto:` nicht feststellbar; `status` ist deshalb immer `handoff_attempted`.
Angelegt durch [`db/init/002_create_mail_history.sql`](../db/init/002_create_mail_history.sql)
(neue Volumes) bzw. beim App-Start (bestehende Datenbanken). Details:
[AP5_EMAIL_HISTORY.md](AP5_EMAIL_HISTORY.md).

| Spalte | Typ | Bedeutung und Regeln |
|---|---|---|
| `id` | Identity-`integer` | Primärschlüssel |
| `handoff_id` | `varchar(32)` | Eindeutige ID der Übergabe; verhindert Doppeleinträge |
| `campaign_id` | `varchar(32)` | Gemeinsame ID aller BCC-Gruppen einer Auswahl |
| `batch_number`, `batch_count` | `integer` | Gruppe *n* von *m* (`1 ≤ n ≤ m`) |
| `created_at` | `timestamptz` | Zeitpunkt der Übergabe |
| `created_by` | `varchar(255)` | Angemeldete Person (E-Mail aus Keycloak); leer ohne Login |
| `subject` | `varchar(255)` | Betreff |
| `body` | `text` | Nachrichtentext |
| `recipients` | `json` | Liste der BCC-Adressen |
| `recipient_count` | `integer` | Anzahl der Adressen, 1 bis 20 |
| `bundeslaender` | `json` | Ländercodes der Empfänger (Dimension Region) |
| `status` | `varchar(32)` | Immer `handoff_attempted` (per CHECK abgesichert) |

## Datenbank starten und prüfen

Im Projektverzeichnis startest du PostgreSQL mit Compose:

```sh
docker compose up -d app-db
```

Vorher muss in `.env` `APP_DB_PASSWORD` mit einem starken Passwort gesetzt sein.
Der Dienst ist nur im internen Docker-Netz erreichbar und veröffentlicht keinen
Host-Port. Das Init-Skript wird beim ersten Start eines neuen Datenbank-Volumes
ausgeführt.

Die Datenbank-Shell öffnest du mit:

```sh
docker compose exec app-db psql -U pl2 -d pflegedb
```

In `psql` kannst du Tabellen und Standard-Leistungen prüfen:

```sql
\dt
SELECT id, name FROM services ORDER BY id;
SELECT id, name, plz, ort FROM centers ORDER BY id;
```

### CSV-Datei importieren

Für die Quelldatei [`app/data/pflegestellen.csv`](../app/data/pflegestellen.csv)
steht das Importskript [`db/import_centers.sql`](../db/import_centers.sql)
bereit. Es importiert die CSV-Felder in `centers` und überträgt die
Leistungs-Checkboxen sowie den Freitext `leistungen` in `services` und
`center_services`.

Führe die folgenden Befehle im Projektverzeichnis aus. Die CSV wird zunächst
in den Datenbankcontainer kopiert; anschließend importiert psql die Datei:

```sh
docker compose cp app/data/pflegestellen.csv app-db:/tmp/pflegestellen.csv
docker compose exec -T app-db psql -v ON_ERROR_STOP=1 -U pl2 -d pflegedb \
  < db/import_centers.sql
```

Der Import kann erneut ausgeführt werden: vorhandene Datensätze mit derselben
`unsere_id` werden aktualisiert, ihre bisherigen Angebotszuordnungen ersetzt.
Andere Datensätze in der Datenbank werden nicht gelöscht. Fehler, etwa
ungültige Zahlen oder Koordinaten außerhalb der Schema-Grenzen, brechen den
Import ab und rollen die Transaktion zurück.

Danach lässt sich das Ergebnis so prüfen:

```sql
SELECT c.id, c.name, c.plz, c.ort, s.name AS angebot
FROM centers AS c
LEFT JOIN center_services AS cs ON cs.center_id = c.id
LEFT JOIN services AS s ON s.id = cs.service_id
ORDER BY c.id, s.name;
```

### Einzelnen Datensatz manuell eintragen

Alternativ können einzelne Pflegestellen manuell eingetragen und mit
vorhandenen Leistungen verknüpft werden:

```sql
INSERT INTO centers (id, name, plz, ort, bundesland)
VALUES (100, 'Beratungsstelle Beispiel', '01067', 'Dresden', 'SN');

INSERT INTO center_services (center_id, service_id)
SELECT 100, id
FROM services
WHERE name IN ('Pflegeberatung', 'Wohnberatung');
```

Die FastAPI-Anwendung liest zur Laufzeit direkt aus `app-db`. Beim Start prüft
sie die Verbindung und das Schema; sie erstellt oder befüllt die Tabellen nicht
selbst. Der ETL-Workflow importiert CSV-Daten mit vorhandener ID und ersetzt
deren Angebotszuordnungen; Datensätze, die in der CSV fehlen, werden nicht
automatisch gelöscht.