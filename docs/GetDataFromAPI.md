# GetDataFromAPI – ETL und Exporte / ETL and exports

## Lokal starten

Im Repositoryordner in PowerShell:

```powershell
python -m pip install -r app/requirements.txt -r requirements-dev.txt
python -m pytest -q
```

Die automatisierten Prüfungen liegen unter `tests`. Der echte Import erzeugt die Datenexporte.

Für den echten vollständigen Import:

```powershell
$env:ZQP_API_URL = 'VOLLSTAENDIGE_HTTPS_API_ADRESSE_AUS_DEM_URSPRUNGSSCRIPT'
python -m GetDataFromAPI
```

Die Adresse enthält einen Token und gehört nicht ins Repository. ETL liest
Shell-Umgebungsvariablen, keine `.env`. Der Vollimport durchsucht 3.339 Rasterpunkte
und benötigt mindestens etwa 17 Minuten zuzüglich Netzlaufzeit. Eine vollständige
Rasterabfrage beweist keine vollständige Abdeckung: Suchradius, Ergebnisbegrenzung,
Paginierung, API-Feldzuordnung und zulässige Nutzungs-/Anfragerate fachlich prüfen.

## Dateien und Vergleich

Nach Erfolg liegen unter `build/GetDataFromAPI`:

| Datei | Inhalt |
| --- | --- |
| `pflegestellen_new.xlsx` / `.json` | Neuer erfolgreicher Gesamtstand |
| `pflegestellen_old.xlsx` / `.json` | Vorheriger erfolgreicher Gesamtstand |
| `pflegestellen_changes.xlsx` / `.json` | Hinzugefügte, entfernte oder feldweise geänderte Werte |
| `pflegestellen_rejected.xlsx` / `.json` | Neue Datensätze ohne Namen, mit Quell-ID und Ablehnungsgrund |
| `pflegestellen.csv` | Neuer Stand im Format des bestehenden App-Loaders |

Beim ersten Lauf dient `app/data/pflegestellen.csv` als alter Stand. Danach wird die
vorherige `new.json` zum Ausgangspunkt und nach Erfolg zu `old`. Dadurch bleiben
auch IDs zwischen ETL-Läufen stabil. `updated_at` zählt nicht als fachliche Änderung.
Excel erhält Postleitzahlen als Text und interpretiert Quelltext nicht als Formel.
JSON erhält numerische IDs, Koordinaten und Leistungsflags.

Nicht wiedergefundene Einrichtungen bleiben bestehen, weil die Rasterquelle keinen
sicheren Löschhinweis liefert; deshalb zeigt ein fehlender Suchtreffer keine Löschung
im Vergleich. Fehlende Kontaktwerte überschreiben keine bekannten Werte. Leistungen
werden weiterhin mit der Stichwortheuristik aus dem ursprünglichen Script erkannt.
Die 627 Bestandsdatensätze ohne Namen bleiben erhalten. Neue namenlose Datensätze
werden ausgesondert und im Prüfbericht sichtbar; andere Validierungsfehler brechen
weiterhin den gesamten Import ab. Die Anzahl im Prüfbericht zählt Quelltreffer,
nicht zwingend eindeutige Einrichtungen.

Alle Ausgaben werden zunächst temporär erstellt. Bei gewöhnlichen Schreibfehlern
werden bereits ersetzte Dateien zurückgesetzt. Dies ist keine transaktionale
Garantie bei Stromausfall/Prozessabsturz. Lokal keine gleichzeitigen Importe auf
denselben Ausgabeordner starten. Ein Extraktionsfehler verändert keine Exportdateien.
CSV und Berichte vor Übernahme fachlich prüfen; Übernahme der CSV in die App erfolgt
per PR und erfolgreichem Deployment, nicht automatisch in eine Live-Datenbank.

## Letztes Artifact lokal abrufen

`scripts/fetch_latest_getdatafromapi_artifact.py` sucht das neueste unverfallene
`pflegestellen-*`-Artifact des Branches `main` in diesem GitHub-Repository. Ist
dessen Artifact-ID noch nicht lokal verarbeitet, wird das ZIP geladen und genau
die enthaltene `pflegestellen.csv` nach `db/temp/pflegestellen.csv` kopiert.
Die ID wird daneben in `.last_getdatafromapi_artifact` gespeichert; wiederholte
Aufrufe laden dasselbe Artifact nicht erneut. Der CSV-Austausch erfolgt erst nach
erfolgreichem Download und Prüfung des ZIP-Inhalts.

```bash
GH_TOKEN=github_token GH_REPO=mbrx387/PL2-HFH \
  python scripts/fetch_latest_getdatafromapi_artifact.py
```

Der Token benötigt Leserechte für Actions-Artifacts (Repository-Berechtigung
`Actions: Read`). Alternativ kann `GITHUB_TOKEN` gesetzt werden. Bei einem
manuellen lokalen Aufruf wird das neueste verfügbare Artifact gegen die lokal
gespeicherte ID verglichen; eine altersabhängige Frischegrenze wird nicht
erzwungen.

Im GitHub-Workflow wird der Abruf nach dem ETL-Export auf `main` mit der
aktuellen `GITHUB_RUN_ID` ausgeführt, damit genau das gerade erzeugte Artifact
verwendet wird. Die bereitgestellte CSV wird zusätzlich als
`pflegestellen-db-temp-*`-Artifact hochgeladen und 90 Tage aufbewahrt. Sie liegt
damit nicht dauerhaft auf dem GitHub-Runner oder automatisch in einer
Produktionsdatenbank. Der geplante Workflow startet samstags um 03:00 UTC
(04:00 MEZ bzw. 05:00 MESZ).

## Pipeline vor dem Merge

`.github/workflows/GetDataFromAPI.yml` prüft relevante Änderungen bei Push auf
`ETL-Prozesse`/`main` sowie bei Pull Requests. Job `validate`: Python 3.12,
Abhängigkeiten installieren, Ruff und alle pytest-Tests.
Die Tests prüfen Wiederholungen, CLI, beschädigte Eingaben, IDs, CSV-Kompatibilität,
Excel/JSON, Differenzen, Rotation und Schutz bei Schreibfehlern. pytest nutzt
`.pytest_tmp` im Projekt, um gesperrte Windows-Tempverzeichnisse zu vermeiden.

Echte Importe laufen nur per `workflow_dispatch` oder samstags 03:00 UTC
(04:00 MEZ / 05:00 MESZ), nach erfolgreicher Validierung.
Zeitpläne werden erst auf dem Default-Branch aktiv und können bei GitHub verzögert
starten. Repository-Secret `ZQP_API_URL` einrichten. Importjob installiert seine
Excel-Abhängigkeit separat aus `GetDataFromAPI/requirements.txt`.

Vor dem Import lädt die Pipeline das jüngste verfügbare Exportartefakt desselben
Branches, damit `old/new` auch auf frischen Runnern erhalten bleiben. Live-Artefakte
werden für bis zu 90 Tage gespeichert (Repository-/Organisationseinstellungen können
die maximale Aufbewahrung begrenzen). Ohne verfügbares Artefakt wird ausdrücklich
auf die versionierte App-CSV zurückgegriffen. Für eine garantiert langfristige
Historie ist ein externer dauerhafter Speicher erforderlich. Kein Produktionsdeployment aus dem ETL-Arbeitsbranch.

Die Workflow-Prüfungen laufen vor dem Merge. Ob GitHub einen Merge bei roten Checks
verhindert, muss zusätzlich ein Repository-Administrator über einen Ruleset bzw.
Branchschutz für `main` mit erforderlichem Check `validate` konfigurieren.

## Fehler und Benachrichtigung

30 Sekunden HTTP-Timeout; höchstens drei Versuche bei Netzwerkfehlern, 429 und 5xx,
mit 1/2 Sekunden Rücksetzpause und 0,3 Sekunden vor jeder Anfrage. Dauerhafte Fehler
werden nicht wiederholt. Ungültige Antworten, Koordinaten oder Basisdateien stoppen
den Import. Maximale Workflow-Laufzeit 180 Minuten; GitHub serialisiert Läufe.

Endgültiger Fehler: Exit-Code 1, roter Actions-Lauf und Fehlerzusammenfassung, kein
neuer Live-Export. GitHub Notifications → Actions für E-Mail/Web-Hinweise aktivieren;
Zustellung hängt von den persönlichen Einstellungen und GitHub-Zustellregeln ab.
Das Script versendet selbst keine Nachrichten. Bei Störung Konfiguration/Quelle
prüfen, Ursache beheben und erneut starten; bei Dauerstörung Verantwortliche
informieren und letzte fachlich geprüfte Daten weiterverwenden. Logs enthalten
keine Quell-URL, Tokens oder Kontaktpayloads.

## Dateien im Code

| Datei | Verantwortung |
| --- | --- |
| `__init__.py` | Kennzeichnet das Paket, startet keinen Import |
| `__main__.py` | CLI-Argumente, Konfiguration, Start und Exit-Code |
| `pipeline.py` | Extraktion, Wiederholungen, Validierung, Zusammenführung |
| `transform.py` | Text-/Kontaktbereinigung, Leistungsheuristik, Feldzuordnung |
| `export.py` | Excel/JSON/CSV, alter/neuer Stand, Differenzen, Veröffentlichung |
| `tests/test_etl_import_validation.py`, `tests/test_excel_json_snapshot_comparison.py` | Automatisierte Tests ohne Live-API |
| `app/main.py` | Separater FastAPI-Web-App-Einstieg, kein ETL-Scheduler |

Stand 22.10.2026: Der vollständige lokale Live-Lauf hat 3.339 Abfragen ausgeführt: 4.092 alte, 4.097 neue Datensätze, 691 Vergleichszeilen und 17 ausgesonderte Treffer. Excel/JSON wurden geöffnet und geprüft; Excel-Datumszellen besitzen das Format dd.mm.yyyy hh:mm:ss. Offen bleiben echter geplanter GitHub-Import und Benachrichtigungszustellung.

---

# English operating guide

Install app and development requirements, then run `python -m pytest -q`.
Tests are located in `tests`. For real extraction set shell variable `ZQP_API_URL`
and run `python -m GetDataFromAPI`; no `.env` loading. The complete grid has 3,339
requests and takes at least 17 minutes of throttling plus network latency.
Confirm source permission, rate limits, field mapping, pagination/radius and coverage.

Successful runs publish old/new/changes/rejected workbooks and JSON plus the app CSV
under `build/GetDataFromAPI`. First old baseline is the app CSV; later runs use the
last successful new JSON. Stable IDs are preserved. Differences ignore timestamps.
Unseen records are retained; absent hits do not imply deletion. Missing contacts do
not erase known values. Keyword-derived service flags require business review.
Existing nameless records remain; new nameless records are quarantined with source
ID/reason. Other invalid records fail the import. Workbooks preserve text postal
codes and prevent source strings being interpreted as Excel formulas.

Exports are staged and rolled back on ordinary write failures, without a multi-file
power-loss transaction guarantee. Do not run concurrent local imports into one folder.
Review CSV and reports before merging data and deploying; there is no direct live DB
synchronization. Branch pushes and PRs run lint and all tests
before merge. Enforcing required checks additionally needs a main branch protection
rule configured by a repository administrator.

Live import runs manually or Saturdays at 03:00 UTC after validation. Set repository
secret `ZQP_API_URL`. Scheduled execution starts on the default branch and can be
delayed. Restore the latest available live artifact from the same branch to retain
state across runners; retention is up to 90 days subject to repository policies.
When none is available, fall back explicitly to app CSV. Permanent history requires
external durable storage.

Requests use a 30-second timeout, at most three attempts for network errors/429/5xx,
1/2-second backoff and 0.3-second throttling. Unrecoverable errors produce exit 1 and
a failed Actions summary without publishing new live exports. Enable personal Actions
notifications and verify delivery. No messages are sent by the script. Escalate
persistent failures and retain last reviewed data. Logs omit endpoint tokens/payloads.

The complete local live run processed 3,339 requests: 4,092 old and 4,097 new records, 691 comparison rows and 17 rejected hits. Excel/JSON were reopened and checked, including Excel date formatting. Scheduled live execution and notification delivery still need verification.


## Automatischer Import in PostgreSQL

Die CSV ist auf `db/import_centers.sql` aus dem Kollegenbranch abgestimmt.
Die 20 Spalten und deren Reihenfolge bleiben erhalten: Semikolon, UTF-8 mit BOM,
Kopfzeile, Beratungsflags 0/1, Koordinaten mit Dezimalpunkt und leere fehlende Werte.
`unsere_id` wird zu `centers.id` (integer), `updated_at` zu
`centers.quelle_updated_at` (timestamp ohne Zeitzone). Bekannte Zeitzonen werden
im CSV-Export nach UTC umgerechnet; historische Zeitstempel ohne Zeitzone bleiben
unverändert. PLZ und Telefonnummern bleiben Text. Details stehen in
`GetDataFromAPI/postgresql_contract.json`.

Nach erfolgreichem ETL-Lauf kopiert der Workflow die CSV auf `main` per SSH/SCP
nach `/opt/pl2-hfh/db/temp/pflegestellen.csv` auf den Deployment-Server. Danach
kopiert er sie in den Container `app-db:/tmp/pflegestellen.csv` und führt dort
das versionierte SQL-Skript mit `psql -v ON_ERROR_STOP=1` aus. Der SQL-Import
läuft transaktional: Datensätze mit bestehender `unsere_id` werden aktualisiert,
neue IDs eingefügt und die Angebotszuordnungen der importierten Stellen ersetzt.
Nicht in der CSV enthaltene Stellen werden nicht gelöscht.

Voraussetzungen auf dem Server:
- `/opt/pl2-hfh` enthält die aktuelle Version des Repositories einschließlich
  `db/import_centers.sql`.
- `docker compose` kennt den laufenden PostgreSQL-Service `app-db` mit Datenbank
  `pflegedb`, Benutzer `pl2` und dem Schema aus `db/init/001_create_centers.sql`.
- GitHub Actions Secrets `SSH_HOST`, `SSH_USER` und `SSH_PRIVATE_KEY` sind wie
  für den Deploy-Workflow eingerichtet; der SSH-Benutzer darf den Compose-Stack
  bedienen.

Das SQL-Skript bricht bei einem Fehler ab; durch `ON_ERROR_STOP` schlägt dann
auch der Workflow fehl. Die Actions-Datei `pflegestellen-db-temp-*` bleibt
zusätzlich 90 Tage als Download verfügbar. Der zeitgesteuerte Workflow läuft
samstags um 03:00 UTC.

Die FastAPI-App liest die Verzeichnisdaten aus derselben PostgreSQL-Datenbank.
Nach erfolgreichem Import stehen Änderungen ohne erneuten App-Start in der UI
zur Verfügung.

```sh
docker compose cp db/temp/pflegestellen.csv app-db:/tmp/pflegestellen.csv
docker compose exec -T app-db psql -v ON_ERROR_STOP=1 -U pl2 -d pflegedb \
  < db/import_centers.sql
```

### PostgreSQL handoff (English)

After a successful ETL run on `main`, the workflow copies the CSV by SSH/SCP to
`/opt/pl2-hfh/db/temp/pflegestellen.csv`, copies it into `app-db`, and runs
`db/import_centers.sql` with `psql -v ON_ERROR_STOP=1`. Existing IDs are updated,
new IDs are inserted, imported centers' service mappings are replaced, and rows
absent from the CSV are not deleted. The server must have the `app-db` Compose
service, the expected schema/database/user, and the existing `SSH_HOST`,
`SSH_USER`, and `SSH_PRIVATE_KEY` Actions secrets. The FastAPI app reads the same
PostgreSQL database, so imported changes become available in the UI without an
app restart.


## CSV am vereinbarten Übergabeort

`python -m GetDataFromAPI` stellt nach erfolgreicher vollständiger Extraktion,
Validierung und Exporterzeugung die neue CSV zusätzlich unter
`app/data/pflegestellen.csv` bereit. Diese Datei wird temporär auf demselben
Dateisystem geschrieben und erst nach vollständigem Schreiben ersetzt. Ein
Abruf-/Validierungsfehler lässt die bisherige Datei unverändert. Bei fehlgeschlagener
Bereitstellung bleiben die bereits erfolgreichen Exporte im Ausgabeordner erhalten;
der CLI-Prozess meldet einen Fehler. Dies ist keine Transaktion über beide Orte.

Excel, JSON und Vergleichsberichte bleiben in `build/GetDataFromAPI`. Mit
`--data-output PFAD` kann die CSV-Übergabe gezielt in einen anderen Ordner erfolgen.
Der Default-Übergabeort ist eine versionierte Datei: Ein erfolgreicher lokaler Lauf
erscheint deshalb als lokale Änderung dieser CSV. Sie wird nicht automatisch committet.
In GitHub Actions erfolgt die Bereitstellung nur im Runner-Arbeitsverzeichnis;
kein automatisches Schreiben in main, auf den Server oder in PostgreSQL. Der Kollege
übernimmt weiterhin den Download/Transport und den Datenbankimport.

### CSV handoff (English)

After a complete successful export, the CLI atomically publishes the validated CSV
at `app/data/pflegestellen.csv` (override with `--data-output`). Reports stay under
build/GetDataFromAPI. A source error preserves the previous handoff file. A handoff
write error leaves the completed report exports available and returns failure.
The runner copy is not an automatic Git commit, server deployment or database import.


## Übergabe ausschließlich als GitHub-Artefakt

Erfolgreiche manuelle und geplante ETL-Läufe stellen CSV, Excel und JSON als
`pflegestellen-<Lauf-ID>` unter Actions → GetDataFromAPI → Lauf → Artifacts bereit.
Die gewünschte Aufbewahrung beträgt 90 Tage, abhängig von Repository-Limits.
Es werden keine Daten-Branches, Daten-Commits oder Daten-Pull-Requests erstellt.
Die Pipeline benötigt keine Repository-/PR-Schreibrechte und löst durch die
Datenbereitstellung kein Deployment aus. Die Einstellung zur PR-Erstellung durch
Actions wird für diese Pipeline nicht benötigt.

Der Kollege lädt das aktuelle erfolgreiche Artefakt manuell oder per eigenem
Sonntagsjob und übernimmt den PostgreSQL-Import. Sein Job soll Lauf-ID und Alter
prüfen, veraltete/fehlgeschlagene Exporte nicht übernehmen und dieselbe Lauf-ID
nicht mehrfach importieren. Dieser Sonntagsjob ist nicht Teil unserer Pipeline.

### Artifact-only handoff (English)

Successful scheduled and manual imports upload the data as a GitHub Actions
artifact. There are no automated data commits, pushes, branches or pull requests.
The import owner downloads the latest successful current export and handles the
PostgreSQL import separately. Repository data delivery does not trigger deployment.
