<!--
# Autor: Gabriel Pfuner (github.com/3mg4, Matrikelnummer: 1142226)
Dieses Dokument erläutert das PostgreSQL-Schema, seine Initialisierung,
die Datenpflege-Sperren und den Import der Pflegestellendaten.
-->

# PostgreSQL-Datenbankschema

**Autor:** Gabriel Pfuner

Diese Dokumentation beschreibt die PostgreSQL-Verbindung der App, das Init-Skript
[`db/init/001_create_centers.sql`](../db/init/001_create_centers.sql), die
Tabellen des Pflegestellenverzeichnisses und den CSV-Import.

## Aufgabe der SQL-Datenbank im System

Die PostgreSQL-Datenbank `pflegedb` ist der dauerhafte Datenspeicher der
Anwendung. Sie enthält das Pflegestellenverzeichnis und dessen Leistungsangebot:
Die App liest diese Daten für Suche, Filter und E-Mail-Empfängerauswahl und
ermöglicht berechtigten Personen, Einträge manuell anzulegen, zu ändern oder
zu deaktivieren. Die Tabellen `centers`, `services` und `center_services`
bilden diese fachlichen Daten ab.

Neue Quelldaten gelangen nicht automatisch durch die ETL-Erzeugung in die
Produktionsdatenbank. Der separate CSV-Import aktualisiert vorhandene
Pflegestellen und ihre Leistungszuordnungen; manuell gesperrte Einträge werden
übersprungen. Die App selbst führt diesen Import nicht aus.

`mail_history` speichert die Übergaben vorbereiteter BCC-E-Mails an das lokale
Mailprogramm, damit die Übergaben später nachvollziehbar und auswertbar sind.
Die Datenbank kann nicht feststellen, ob eine Person die E-Mail im Mailprogramm
tatsächlich abgeschickt hat; die Person kann den Versand aber nachträglich in
der Versandhistorie bestätigen (`delivery_status`). Benutzerkonten und Anmeldedaten liegen nicht in
`pflegedb`: Keycloak verwendet dafür einen eigenen Datenbankdienst.

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
automatisch. Ausnahmen (jeweils nur wenn nötig, beim Start angelegt): die
AP5-Tabelle `mail_history` (siehe unten) und die Sperrvermerk-Spalten aus
`db/init/003_manual_maintenance.sql` (Issue #85, siehe
[`app/maintenance.py`](../app/maintenance.py)).

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
| `manuell_gepflegt` | `boolean` | Sperrvermerk gegen den Import (Issue #85); Standard `false` |
| `manuell_geaendert_von` | `varchar(255)` | Keycloak-Loginname (`preferred_username`), ersatzweise E-Mail, der letzten manuellen Änderung |
| `manuell_geaendert_am` | `timestamptz` | Zeitpunkt der letzten manuellen Änderung |
| `quelle_updated_at` | `timestamp` | Änderungszeitpunkt in der Quelldatei |
| `created_at` | `timestamptz` | Zeitpunkt der Anlage; standardmäßig aktuelle Zeit |
| `updated_at` | `timestamptz` | Zeitpunkt der Änderung; standardmäßig aktuelle Zeit |

### Sperrvermerk für manuell gepflegte Einrichtungen (Issue #85)

[`db/init/003_manual_maintenance.sql`](../db/init/003_manual_maintenance.sql)
ergänzt die Tabelle `centers` um `manuell_gepflegt`,
`manuell_geaendert_von` und `manuell_geaendert_am`. Das SQL-Skript ist
idempotent und wird vom PostgreSQL-Docker-Image nur beim erstmaligen Anlegen
eines leeren Datenbank-Volumes ausgeführt. Bei bereits vorhandenen Datenbanken
legt die App beim Start dieselben fehlenden Spalten über
[`app/maintenance.py`](../app/maintenance.py) an. Eine transaktionale
PostgreSQL-Advisory-Lock-Sperre verhindert Konflikte, wenn mehrere
Gunicorn-Worker gleichzeitig starten.

Beim Start werden außerdem vorhandene Einträge mit `id >= 1.000.000` als
manuell gepflegt markiert. Diese Altbestände erhalten keinen nachträglichen
Änderungsbenutzer oder -zeitpunkt; beide Werte bleiben `NULL`, weil diese
Informationen nicht zuverlässig bekannt sind.

Die Sperre schützt manuell bearbeitete Datensätze vor dem ETL-Import:

- Die API vergibt für neue manuelle Einträge IDs ab `1.000.000` und setzt den
  Sperrvermerk. Bei manuellen Änderungen werden zusätzlich Benutzername
  (ersatzweise E-Mail) und Änderungszeitpunkt gespeichert. Das Deaktivieren
  einer Einrichtung setzt ebenfalls den Sperrvermerk.
- `db/import_centers.sql` überspringt Importzeilen, die zu einem gesperrten
  Datensatz passen – anhand der internen ID, der `zqp_id` oder des Schlüssels
  aus Name, Adresse, PLZ und Ort. Dabei bleiben dessen Felder und
  Leistungszuordnungen unverändert; die Zahl übersprungener Zeilen erscheint
  als `NOTICE` im Import-Log.
- IDs ab `1.000.000` sind für manuelle Einträge reserviert. Taucht eine solche
  ID in der Import-CSV auf, bricht der Import mit einem Fehler ab. Über
  `DELETE /api/centers/{center_id}/manual-lock` kann die Redaktion den
  Sperrvermerk entfernen; ein späterer Import kann den Datensatz dann wieder
  aus der Quelle aktualisieren.

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
| `created_by` | `varchar(255)` | Angemeldete Person (E-Mail, Name oder ID aus der Keycloak-Sitzung); leer ohne Login |
| `subject` | `varchar(255)` | Betreff |
| `body` | `text` | Nachrichtentext |
| `recipients` | `json` | Liste der BCC-Adressen |
| `recipient_count` | `integer` | Anzahl der Adressen, 1 bis 20 |
| `bundeslaender` | `json` | Ländercodes der Empfänger (Dimension Region) |
| `status` | `varchar(32)` | Immer `handoff_attempted` (per CHECK abgesichert) |
| `delivery_status` | `varchar(16)` | Manuelle Versandbestätigung: leer = offen, `sent` oder `not_sent` (per CHECK abgesichert) |
| `delivery_confirmed_at` | `timestamptz` | Zeitpunkt der Markierung |
| `delivery_confirmed_by` | `varchar(255)` | Person, die markiert hat |

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
vorhandenen Leistungen verknüpft werden. Manuelle Einträge müssen eine ID
**ab 1.000.000** verwenden (dieser Bereich gehört der Datenpflege; der Import
bricht ab, falls eine CSV dort eine ID liefern würde). Beim Anlegen über die
API (`POST /api/centers`) vergibt der Server die ID automatisch und setzt den
Sperrvermerk; bei manuellem SQL-Eintrag entsprechend selbst setzen:

```sql
INSERT INTO centers (id, name, plz, ort, bundesland, manuell_gepflegt)
VALUES (1000000, 'Beratungsstelle Beispiel', '01067', 'Dresden', 'SN', true);

INSERT INTO center_services (center_id, service_id)
SELECT 1000000, id
FROM services
WHERE name IN ('Pflegeberatung', 'Wohnberatung');
```

Die FastAPI-Anwendung liest zur Laufzeit direkt aus `app-db`. Beim Start prüft
sie die Verbindung und das Schema; sie erstellt oder befüllt die Tabellen nicht
selbst (Ausnahme: `mail_history` und die Sperrvermerk-Spalten aus
`db/init/003_manual_maintenance.sql`, die sie anlegt, falls sie fehlen). Der
Import (Server-Cron, siehe `docs/GetDataFromAPI.md`) spielt CSV-Daten mit
vorhandener ID ein, ersetzt deren Angebotszuordnungen und **überspringt
gesperrte Einträge vollständig**; Datensätze, die in der CSV fehlen, werden
nicht automatisch gelöscht.
