# GetDataFromAPI – ETL und Exporte / ETL and exports

## Lokal starten

Im Repositoryordner in PowerShell:

```powershell
python -m pip install -r app/requirements.txt -r requirements-dev.txt
python -m pytest -q
python -m GetDataFromAPI.demo
```

Die Demo ruft keine API ab und erzeugt klar bezeichnete Beispieldateien unter
`build/GetDataFromAPI/demo`. Sie verändert keine Live-Exporte.

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

## Pipeline vor dem Merge

`.github/workflows/GetDataFromAPI.yml` prüft relevante Änderungen bei Push auf
`ETL-Prozesse`/`main` sowie bei Pull Requests. Job `validate`: Python 3.12,
Abhängigkeiten installieren, Ruff, alle pytest-Tests, Offline-Demo und Artefakt
`example-exports-<run-id>` zum Download vor dem Merge.
Die Tests prüfen Wiederholungen, CLI, beschädigte Eingaben, IDs, CSV-Kompatibilität,
Excel/JSON, Differenzen, Rotation und Schutz bei Schreibfehlern. pytest nutzt
`.pytest_tmp` im Projekt, um gesperrte Windows-Tempverzeichnisse zu vermeiden.

Echte Importe laufen nur per `workflow_dispatch` oder samstags 02:00 UTC
(03:00 Winterzeit / 04:00 Sommerzeit in Wien), nach erfolgreicher Validierung.
Zeitpläne werden erst auf dem Default-Branch aktiv und können bei GitHub verzögert
starten. Repository-Secret `ZQP_API_URL` einrichten. Importjob installiert seine
Excel-Abhängigkeit separat aus `GetDataFromAPI/requirements.txt`.

Vor dem Import lädt die Pipeline das jüngste verfügbare Exportartefakt desselben
Branches, damit `old/new` auch auf frischen Runnern erhalten bleiben. Live-Artefakte
werden für bis zu 90 Tage gespeichert (Repository-/Organisationseinstellungen können
die maximale Aufbewahrung begrenzen). Ohne verfügbares Artefakt wird ausdrücklich
auf die versionierte App-CSV zurückgegriffen. Für eine garantiert langfristige
Historie ist ein externer dauerhafter Speicher erforderlich. Demo-Artefakte zählen
nicht als Live-Baseline. Kein Produktionsdeployment aus dem ETL-Arbeitsbranch.

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
| `demo.py` | Reproduzierbare Offline-Demonstration |
| `test_pipeline.py`, `test_export.py` | Automatisierte Tests ohne Live-API |
| `app/main.py` | Separater FastAPI-Web-App-Einstieg, kein ETL-Scheduler |

Stand 22.10.2026: 68 lokale Tests auf Windows/Python 3.14 und Ruff erfolgreich.
Live-Stichprobe: drei Suchpunkte, 4.092 alte und 4.113 zusammengeführte neue
Datensätze, 21 Vergleichszeilen, drei ausgesonderte Treffer. Alle erzeugten Excel-
und JSON-Dateien wieder geöffnet und geprüft. Kein vollständiger Deutschlandimport.
Offen: GitHub-Ausführung, echte Cron-Auslösung, Benachrichtigungszustellung,
fachliche Vollabnahme. Docker lokal nicht verfügbar.

---

# English operating guide

Install app and development requirements, then run `python -m pytest -q`.
`python -m GetDataFromAPI.demo` creates isolated offline examples in
`build/GetDataFromAPI/demo`. For real extraction set shell variable `ZQP_API_URL`
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
synchronization. Branch pushes and PRs run lint, all tests and an offline demo artifact
before merge. Enforcing required checks additionally needs a main branch protection
rule configured by a repository administrator.

Live import runs manually or Saturdays at 02:00 UTC after validation. Set repository
secret `ZQP_API_URL`. Scheduled execution starts on the default branch and can be
delayed. Restore the latest available live artifact from the same branch to retain
state across runners; retention is up to 90 days subject to repository policies.
When none is available, fall back explicitly to app CSV. Permanent history requires
external durable storage. Demo artifacts never serve as live baselines.

Requests use a 30-second timeout, at most three attempts for network errors/429/5xx,
1/2-second backoff and 0.3-second throttling. Unrecoverable errors produce exit 1 and
a failed Actions summary without publishing new live exports. Enable personal Actions
notifications and verify delivery. No messages are sent by the script. Escalate
persistent failures and retain last reviewed data. Logs omit endpoint tokens/payloads.

68 local tests passed on Windows/Python 3.14. A three-point live sample produced
4,113 merged records, 21 changes and three quarantined hits; workbooks/JSON were
reopened and checked. Full national extraction, hosted workflow, cron delivery,
notifications and business acceptance remain pending. Docker unavailable locally.
