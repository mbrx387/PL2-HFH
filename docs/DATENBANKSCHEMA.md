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
zum ersten Mal mit einer leeren Datenbank initialisiert wird. Die App wartet
beim Start auf eine erreichbare Datenbank samt `centers`-Tabelle, legt das
Schema aber nicht selbst an und importiert keine CSV-Datei automatisch.

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

## Datenbank starten und prüfen

Im Projektverzeichnis startest du App und PostgreSQL gemeinsam:

```sh
docker compose up -d --build app
```

Compose verbindet die App intern mit `app-db:5432`. Das Passwort wird über
`APP_DB_PASSWORD` aus `.env` als `PGPASSWORD` an die App gereicht. Die App
wartet auf den erfolgreichen Healthcheck der Datenbank.

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

Die API verwendet PostgreSQL direkt. SQLite wird ausschließlich für die
isolierten API-Tests genutzt. Ein CSV-Import aktualisiert Datensätze mit
vorhandener ID und deren Angebotszuordnungen; Datensätze, die in der CSV fehlen,
werden nicht automatisch gelöscht.
