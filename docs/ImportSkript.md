<!--
# Autor: Gabriel Pfuner (github.com/3mg4)
Dieses Dokument bündelt die Hinweise zur Einrichtung und Verwendung der
Import-, Cron- und Backup-Skripte für den Betrieb der Anwendung.
-->

# Import- und Wartungsskripte

Diese Anleitung beschreibt die Server-Skripte für den Import der aktuellen
Pflegestellen-CSV, die Einrichtung des Import-Cronjobs und Backups der beiden
PostgreSQL-Datenbanken.

## Voraussetzungen

- Das Repository liegt auf dem Server unter `/opt/pl2-hfh` oder der
  `PROJECT_DIR`-Variable wird passend gesetzt.
- Docker Compose ist eingerichtet und der ausführende Benutzer darf Docker
  verwenden.
- Für den Datenimport ist `app-db` mit Datenbank `pflegedb` erreichbar. Für
  Backups müssen `app-db` und `keycloak-db` laufen; Keycloak wird über das
  Compose-Profil `sso` aktiviert.

## `import_latest_centers.sh`

Das Skript importiert die neueste CSV, die der ETL-Workflow nach
`db/temp/pflegestellen.csv` auf dem Server kopiert hat:

```sh
cd /opt/pl2-hfh
./scripts/import_latest_centers.sh
```

Es schreibt ein fortlaufendes Log nach
`/var/log/pl2-hfh/import-centers.log`. Vor dem Import prüft es:

- Ob die CSV vorhanden und nicht leer ist.
- Ob dieselbe CSV bereits importiert wurde. Dazu vergleicht es ihren SHA-256-
  Hash mit `db/temp/.last_imported`.
- Ob die Datenbank erreichbar und kein anderer Importlauf aktiv ist.

Anschließend stellt es die Sperrvermerk-Spalten sicher, kopiert die CSV in den
Datenbankcontainer und führt `db/import_centers.sql` mit `ON_ERROR_STOP` aus.
Der Import erfolgt transaktional. Manuell gesperrte Einträge werden
übersprungen; Details dazu stehen in
[DATENBANKSCHEMA.md](DATENBANKSCHEMA.md#sperrvermerk-für-manuell-gepflegte-einrichtungen-issue-85).
Der Hash-Marker wird erst nach erfolgreichem Import aktualisiert. Bei einem
Fehler wird die CSV beim nächsten Lauf erneut versucht.

`PROJECT_DIR`, `LOG_DIR` und `LOCK_FILE` können beim manuellen Aufruf als
Umgebungsvariablen überschrieben werden. Die Cron-Einrichtung steht im
folgenden Abschnitt.

## `setup_import_cron.sh`

Dieses Skript richtet den wöchentlichen Import über `/etc/cron.d` ein. Es muss
mit Root-Rechten ausgeführt werden:

```sh
cd /opt/pl2-hfh
sudo ./scripts/setup_import_cron.sh
```

Standardmäßig legt es `/etc/cron.d/pl2-hfh-import` mit folgendem Eintrag an:

```cron
0 6 * * 6 root /opt/pl2-hfh/scripts/import_latest_centers.sh
```

Das ist für Samstag um 06:00 UTC vorgesehen. Cron verwendet die Zeitzone des
Servers; daher vor dem Einrichten prüfen, ob der Server auf UTC läuft, oder
die Stunde im Eintrag anpassen. Ist bereits ein Eintrag für das Importskript
vorhanden, lässt das Setup-Skript die Datei unverändert. Nach manuellen
Änderungen an der Zeitzone oder am Projektpfad den Eintrag in
`/etc/cron.d/pl2-hfh-import` kontrollieren.

## `backup_db.sh`

Das Skript erstellt je einen PostgreSQL-Custom-Format-Dump der App-Datenbank
`pflegedb` und der Keycloak-Datenbank `keycloak`. Beide Datenbankcontainer
müssen laufen:

```sh
cd /opt/pl2-hfh
docker compose --profile sso up -d app-db keycloak-db
chmod 700 scripts/backup_db.sh
./scripts/backup_db.sh
```

Die Dumps werden standardmäßig unter `/var/backups/pl2-hfh/` mit UTC-Zeitstempel
gespeichert:

- `pflegedb-<Zeitstempel>.dump`
- `keycloak-<Zeitstempel>.dump`

Vor der Fertigstellung prüft das Skript jeden Dump mit `pg_restore --list`.
Das Backup-Verzeichnis erhält die Rechte `700`, die Dump-Dateien `600`.
Die temporäre lokale Dump-Datei wird bei Fehlern aufgeräumt; erst nach
erfolgreicher Prüfung wird sie unter dem endgültigen Dateinamen abgelegt.
Standardmäßig bleiben Backups 14 Tage erhalten; ältere passende Dumps werden
gelöscht. Die Werte lassen sich beim Aufruf überschreiben:

```sh
BACKUP_DIR=/sicherer/pfad RETENTION_DAYS=30 ./scripts/backup_db.sh
```

Das Skript erstellt **keinen Cronjob**. Ein Beispiel für den täglichen Aufruf
um 03:30 Uhr und Anleitungen zum Wiederherstellen und Testen stehen in
[keycloak/README.md](../keycloak/README.md#11-backups-und-wiederherstellung).
Die Backups enthalten Datenbankinhalte und sind vertraulich. Sie liegen
zunächst nur auf dem Server; eine zusätzliche Kopie an einem getrennten,
sicheren Speicherort muss separat eingerichtet werden. `.env`-Dateien,
Zertifikate und Docker-Volumes werden nicht gesichert.
