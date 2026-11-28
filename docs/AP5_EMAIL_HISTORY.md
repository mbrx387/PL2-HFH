# E-Mail-Zentrale & Versandhistorie (AP5) – die Poststelle unserer App

Diese Seite erklärt in einfachen Worten, wie der Pflegezentren-Finder E-Mails
an viele Pflegeeinrichtungen vorbereitet, warum der Server dabei selbst keine
E-Mail verschickt und wie jede Übergabe dokumentiert wird. Sie ist zugleich
das Handout zu Arbeitspaket 5 und zeigt, wer welchen Teil gebaut hat
([Abschnitt 6](#6-wer-hat-was-gemacht)). Fachbegriffe stehen im
[Glossar](#13-glossar).

| | |
|---|---|
| Arbeitspaket | **AP5 – E-Mail-Kommunikationsmodul & Historisierung** (Issue #20) |
| Beteiligt | **Adrian** (Konzept, Backend, Tests, Versandbestätigung, Auswertung nach Zeit und Region, Doku) · **Inaara** (Anbindung an die neue Oberfläche, Rollenprüfung, Abstimmung mit Prof. Waage) |
| Stand | 28.11.2026 |

## Inhalt

1. [AP5 in einem Bild](#1-ap5-in-einem-bild)
2. [Was AP5 leistet](#2-was-ap5-leistet)
3. [So wird es bedient](#3-so-wird-es-bedient)
4. [Der Weg einer E-Mail](#4-der-weg-einer-e-mail)
5. [Warum wir es so gelöst haben](#5-warum-wir-es-so-gelöst-haben)
6. [Wer hat was gemacht](#6-wer-hat-was-gemacht)
7. [Die Dateien](#7-die-dateien)
8. [Schnittstelle (API)](#8-schnittstelle-api)
9. [Datenbank und Update auf dem Server](#9-datenbank-und-update-auf-dem-server)
10. [Datenschutz](#10-datenschutz)
11. [Tests](#11-tests)
12. [Grenzen und Ausblick](#12-grenzen-und-ausblick)
13. [Glossar](#13-glossar)

---

## 1. AP5 in einem Bild

Stell dir die App als Büro mit einer **Poststelle** vor:

| In der Poststelle | Bei uns |
|---|---|
| 📇 Die Poststelle hat das **Adressbuch** aller Einrichtungen | Die Adressen kommen aus der Datenbank (`centers.email`), nicht aus dem Browser |
| ✍️ Du schreibst **einen Brief** und sagst, wer ihn bekommen soll | Betreff und Text in der **E-Mail-Zentrale**, Empfänger per Häkchen oder Filter |
| 🙈 Jeder Umschlag geht **verdeckt** raus, niemand sieht die anderen Empfänger | Alle Adressen stehen im **BCC**, nie in „An“ oder „CC“ |
| 📦 In einen Umschlag passen höchstens **20 Adressen** | Große Auswahlen werden in **Teile** mit je höchstens 20 Adressen aufgeteilt |
| 📮 Einwerfen musst du **selbst**, am eigenen Briefkasten | Die App öffnet dein **eigenes Mailprogramm** (`mailto:`). Der Server verschickt nichts |
| 📒 Die Poststelle führt ein **Postbuch**: was, wann, an wie viele, von wem | Jede Übergabe landet in der **Versandhistorie** (Tabelle `mail_history`) |
| 🔎 Im Postbuch blätterst du nach **Monat, Quartal, Jahr** und **Bundesland** | Filter in der Versandhistorie, dazu **Details** zu jedem Eintrag |
| ✅ Später hakst du im Buch ab: **eingeworfen** oder **liegen geblieben** | **Versandbestätigung**: „Versendet“ oder „Nicht versendet“ |

Die Poststelle sieht nicht, ob du den Umschlag wirklich einwirfst. Deshalb
heißt ein neuer Eintrag immer **„übergeben“**. Erst deine Bestätigung macht
daraus **„versendet“**.

---

## 2. Was AP5 leistet

| Anforderung (Detailanforderungen PL2, „E-Mail-Funktionen“) | Umsetzung |
|---|---|
| Automatische Übernahme der E-Mail-Adressen aus der Datenbank | Der Browser schickt nur Einrichtungs-IDs oder Filter. Der Server liest die Adressen selbst aus `centers.email`. Felder mit mehreren Adressen (`a@x.de; b@x.de`) werden aufgeteilt. |
| Auswahl einzelner oder mehrerer Empfänger | Häkchen bei einzelnen Einrichtungen oder alle Treffer der aktuellen Filter (Suche, Bundesland, Angebot), auch über die angezeigten Seiten hinaus. |
| Versand über das eigene Mailprogramm, als BCC | `mailto:`-Link nur mit `bcc=`. Höchstens **20** Adressen und **1.800** Zeichen Linklänge pro E-Mail. Jeder Teil öffnet sich nur durch einen eigenen Klick. |
| Historisierung inkl. Anzahl der Empfänger | Zeitpunkt, Betreff, Text, BCC-Adressen, Anzahl, Teil *n/m*, Bundesländer und angemeldete Person je Übergabe. |
| Dokumentation versendeter Nachrichten | Ansicht **Versandhistorie**: je Eintrag **Details** mit Nachrichtentext, BCC-Empfängern, Bundesländern und Person. Suche in Betreff und Text. **Versandbestätigung** (wurde die Mail wirklich verschickt?). |
| Notwendige Dimensionen: Zeit (Kalenderjahr, Quartal, Monat), Region (Bundesland, Kreis) | Filter nach **Jahr, Quartal und Monat** sowie nach **Bundesland**. Über der Tabelle steht, wie viele Übergaben und Empfänger der Filter umfasst. Den **Kreis** gibt es in den Einrichtungsdaten nicht (siehe [Abschnitt 12](#12-grenzen-und-ausblick)). |

Außerdem: Doppelte Adressen werden nur einmal angeschrieben (Groß- und
Kleinschreibung egal). Einrichtungen ohne gültige Adresse werden übersprungen
und in der Vorschau gezählt.

---

## 3. So wird es bedient

1. **Einrichtungen:** Einrichtungen anhaken **oder** nur Filter setzen
   (Suchbegriff, Angebot, Bundesland). Angehakte Einrichtungen haben Vorrang.
   Ohne Häkchen gelten alle Treffer der Filter.
2. **E-Mail-Zentrale:** Betreff (Pflicht) und Nachricht eintragen, dann
   **„E-Mail vorbereiten“**. Die App zeigt, wie viele Empfänger in wie viele
   Teile aufgeteilt werden.
3. Für jeden Teil gibt es einen Button **„Teil n öffnen (x Empfänger)“**. Ein
   Klick öffnet das Mailprogramm mit diesem Teil im BCC und legt einen Eintrag
   in der Versandhistorie an. Abschicken muss die Person im Mailprogramm selbst.
4. **Versandhistorie:** Nach dem Senden den Eintrag als **„Versendet“** oder
   **„Nicht versendet“** markieren. **„Zurücksetzen“** macht das rückgängig.
   Oben steht, wie viele Einträge noch nicht bestätigt sind.
5. **Auswerten:** Filter nach **Jahr** und **Zeitraum** (Quartal oder Monat),
   **Bundesland**, **Versand** (zum Beispiel „Noch offen“) und Suche in Betreff
   und Text. Über der Tabelle steht, wie viele Übergaben und Empfänger der
   Filter umfasst. **„Details anzeigen“** zeigt Nachricht, Empfänger,
   Bundesländer und Person. Es werden je 50 Einträge geladen, **„Weitere
   Einträge laden“** holt die nächsten.

**Beispiel (echte Daten, Stand November 2026):** Bremen hat 30 Einrichtungen.
Nach dem Prüfen und Entfernen doppelter Adressen bleiben 29 Empfänger. Daraus
werden **2 Teile** (20 + 9 Empfänger), also zwei Klicks und zwei Einträge in
der Historie.

---

## 4. Der Weg einer E-Mail

```
 Browser                       Server (FastAPI)               Datenbank
 -------                       ----------------               ---------
 1) "E-Mail vorbereiten"
    IDs oder Filter  -------->  liest Adressen, prüft,  <---  centers
                                entfernt Doppelte,
                                teilt in Teile (max. 20)
    Teile + signierter  <-----  (noch kein Eintrag)
    "Übergabe-Zettel"

 2) Klick "Teil 1 öffnen"
    Übergabe-Zettel  -------->  prüft Signatur und Alter,
                                schreibt genau 1 Eintrag  --> mail_history
    mailto:-Link     <-------
    -> Mailprogramm öffnet sich, Adressen stehen im BCC
    -> die Person prüft und schickt selbst ab

 3) Versandhistorie
    "Versendet"      -------->  speichert Markierung,     --> mail_history
                                Zeitpunkt und Person
```

Der „Übergabe-Zettel“ (Token) enthält Adressen, Betreff und Text als feste
Momentaufnahme. Er ist mit dem `SECRET_KEY` der App signiert und eine Stunde
gültig. So kann niemand zwischen Schritt 1 und 2 Adressen oder Text
austauschen.

---

## 5. Warum wir es so gelöst haben

| Entscheidung | Andere Möglichkeit | Warum so |
|---|---|---|
| Versand über das **eigene Mailprogramm** (`mailto:`) | Versand über einen Mailserver der HFH (SMTP) | Entspricht der Vorgabe „über die eigene Standardmailbox“. Der Server braucht keine Mail-Zugangsdaten und kann nicht als Spam-Schleuder missbraucht werden. Prof. Waage hat am 20.11.2026 bestätigt, dass das eigene Mailprogramm ausreicht. |
| **Nur BCC** | Adressen in „An“ oder „CC“ | Datenschutz: Die Einrichtungen sehen die anderen Empfänger nicht. |
| **Höchstens 20 Adressen und 1.800 Zeichen** je E-Mail | Alle Adressen in eine E-Mail | Mailprogramme kürzen zu lange `mailto:`-Links (Outlook ab etwa 2.000 Zeichen), und E-Mails mit sehr vielen Empfängern landen leichter im Spam. Kleine Teile lassen sich vor dem Senden besser prüfen. |
| **Der Server** holt die Adressen | Der Browser schickt die Adressen mit | Niemand kann über die Oberfläche fremde Adressen einschleusen. Unbekannte Felder lehnt der Server ab. |
| Eintrag heißt **„übergeben“**, Versand wird **von Hand bestätigt** | Eintrag gleich als „versendet“ speichern | Bei `mailto:` kann keine Webanwendung sehen, ob wirklich gesendet wurde. Wir dokumentieren ehrlich statt etwas Falsches zu behaupten. Die Bestätigung von Hand war ein Wunsch von Prof. Waage (20.11.2026). |
| **Ein Eintrag pro Klick** | Eintrag schon beim Vorbereiten | In der Historie steht nur, was wirklich an das Mailprogramm ging. Ein doppelter Klick erzeugt keinen doppelten Eintrag. |
| Tabelle wird **beim App-Start** angelegt, mit Sperre | Nur über die SQL-Datei in `db/init/` | Die SQL-Dateien laufen nur bei einer neuen, leeren Datenbank. Der Server hat aber schon Daten. Die Sperre verhindert, dass zwei gleichzeitig startende Worker abstürzen (im Test ohne Sperre: bis zu 7 von 8 Abstürze). Dasselbe Muster wird inzwischen auch für Issue #85 genutzt (`app/maintenance.py`). |
| Felder mit **mehreren Adressen aufteilen** | Nur die erste Adresse nehmen | In den echten Daten haben 570 von 3.806 Einrichtungen mit Adresse (15 %) mehrere Adressen in einem Feld. Ohne Aufteilung wären diese Links kaputt. |

---

## 6. Wer hat was gemacht

| Teilleistung | Wer | Nachweis |
|---|---|---|
| Konzept (mailto, BCC-Aufteilung, Historie). Backend: Adressen aus der Datenbank, Prüfen und Aufteilen, signierte Übergabe, Tabelle `mail_history` mit sicherem Anlegen beim Start, Schnittstelle `/api/mail…`. Tests mit SQLite und PostgreSQL. Dokumentation. | Adrian | PR #47 (30.10.2026), in PR #83 übernommen |
| Anbindung der neuen Oberfläche an AP5 (E-Mail-Zentrale mit Teilen, Versandhistorie; Seitenlayout aus dem Frontend-Design, PR #58), Rollenprüfung (`read_centers`), Zusammenführung nach `main` | Inaara | PR #83, gemergt am 21.11.2026 |
| Abstimmung mit Prof. Waage: eigenes Mailprogramm reicht, Versandbestätigung als optionaler Wunsch | Inaara (Fragen vorbereitet von Adrian) | 20.11.2026 |
| Korrektur von PR #83: zwei Syntaxfehler, die die Tests blockierten, und Tests für die Rollen | Adrian | Commit `811627f` (20.11.2026) |
| Versandbestätigung: Buttons, Zähler, Schnittstelle, automatisches Datenbank-Update, Tests | Adrian | Branch `AP5-Versandbestaetigung`, Teil 1 und 2 (28.11.2026) |
| Auswertung der Historie nach Zeit (Jahr, Quartal, Monat) und Region (Bundesland), Summe der Empfänger, Detailansicht, Suche, „Weitere Einträge laden“, Tests. Überarbeitung dieser Seite | Adrian | Branch `AP5-Versandbestaetigung`, Teil 2 bis 4 (28.11.2026) |

---

## 7. Die Dateien

| Datei | Aufgabe |
|---|---|
| `app/mail_service.py` | Adressen aus der Datenbank holen, prüfen, Doppelte entfernen, in Teile aufteilen, `mailto:`-Link bauen |
| `app/routers/mail.py` | Schnittstelle: vorbereiten, übergeben, Historie lesen, Versand bestätigen |
| `app/mail_models.py` | Tabelle `mail_history`, sicheres Anlegen und Ergänzen beim Start |
| `app/mail_schemas.py` | Prüfung aller Ein- und Ausgaben der Schnittstelle |
| `app/config.py` | Grenzwerte `MAIL_BCC_BATCH_SIZE` (20) und `MAIL_MAX_MAILTO_LENGTH` (1.800) |
| `db/init/002_create_mail_history.sql` | Tabelle für neue, leere Datenbanken |
| `app/templates/index.html`, `app/static/js/main.js`, `app/static/css/style.css` | Oberfläche: E-Mail-Zentrale und Versandhistorie |
| `tests/test_mail.py`, `tests/test_mail_postgres.py` | Automatische Tests (siehe [Abschnitt 11](#11-tests)) |
| `docs/AP5_EMAIL_HISTORY.md` | Diese Seite |

---

## 8. Schnittstelle (API)

Alle Endpunkte liegen unter `/api`. Sie verlangen einen Login und die
Berechtigung `read_centers` (Rollen reader, editor, admin).

| Endpunkt | Zweck |
|---|---|
| `POST /api/mail/prepare` | Empfänger ermitteln und aufteilen. Antwort: Zähler und je Teil `number`, `recipient_count`, `bundeslaender`, `handoff_token`. **Schreibt noch nichts.** |
| `POST /api/mail/handoff` | Token prüfen, **einen** Historieneintrag schreiben, `mailto_url` zurückgeben. Derselbe Token erzeugt auch beim zweiten Mal nur einen Eintrag. |
| `GET /api/mail-history` | Historie, neueste zuerst. Filter: `limit` (1–200), `offset`, `year`, `quarter` (1–4) oder `month` (1–12, beide nur mit `year`), `bundesland` (z. B. `HB`), `search`, `campaign_id`, `delivery` (`open`, `sent`, `not_sent`). Antwort: `total`, `recipient_total` (Summe der Empfänger im Filter), `items` |
| `PUT /api/mail-history/{id}/delivery` | Versand bestätigen: `{"delivery_status": "sent"}`, `"not_sent"` oder `null` (zurücksetzen). Speichert Zeitpunkt und Person. |

Beispiel für `prepare`:

```json
{"filters": {"bundesland": "HB"}, "subject": "Einladung", "body": "Guten Tag"}
```

oder mit Häkchen: `{"center_ids": [10, 30], "subject": "Einladung"}`.
Unbekannte Felder (zum Beispiel eigene Adressen) lehnt der Server mit 422 ab,
unbekannte Historieneinträge mit 404. Der Token ist signiert, aber **nicht
verschlüsselt**: nicht in Logs oder URLs ablegen.

---

## 9. Datenbank und Update auf dem Server

AP5 nutzt die vorhandene PostgreSQL-Datenbank `app-db`. Es gibt keine zweite
Datenbank, kein neues Volume und keine Änderung an `centers`, `services` oder
`center_services`. Die Spalten stehen in
[DATENBANKSCHEMA.md](DATENBANKSCHEMA.md#mail_history-ap5).

- **Neue, leere Datenbank:** `db/init/002_create_mail_history.sql` legt die
  Tabelle an.
- **Bestehende Datenbank (Server):** Docker führt `db/init/` dort nicht erneut
  aus. Deshalb legt die App beim Start die Tabelle an, falls sie fehlt
  (`ensure_mail_history_table`). Fehlen nur die drei Spalten der
  Versandbestätigung, ergänzt die App sie (`ALTER TABLE … ADD COLUMN`) samt
  Prüfregel. Vorhandene Einträge bleiben erhalten und gelten als „offen“.
- Beides läuft unter einer PostgreSQL-Sperre (`pg_advisory_xact_lock`), damit
  gleichzeitig startende Worker sich nicht in die Quere kommen.
- Fehlen Kernspalten (unbekannte, veraltete Tabelle), startet die App mit einer
  klaren Fehlermeldung nicht.
- Die Datenbank erzwingt per Prüfregel (CHECK): höchstens 20 Empfänger je
  Eintrag, Status immer `handoff_attempted`, Versandmarkierung nur leer,
  `sent` oder `not_sent`.
- **Keine Volumes löschen, keine Datenbank zurücksetzen.** Zurückrollen geht
  durch einen Code-Rollback. Die zusätzlichen Spalten stören die alte Version
  nicht.

---

## 10. Datenschutz

Die Historie speichert E-Mail-Adressen (teils personenbezogen, zum Beispiel
`vorname.nachname@…`), Nachrichtentexte und die angemeldete Person.

- **Zugriff:** Alle angemeldeten Rollen (reader, editor, admin) dürfen die
  Historie lesen und den Versand markieren. Ob das so bleibt, regelt das
  Rechtekonzept des Teams.
- **Aufbewahrung:** Es gibt noch keine automatische Löschung. Eine Frist (zum
  Beispiel 12 Monate) sollte das Team mit den Projektverantwortlichen festlegen.
- Mail-Texte sollten keine sensiblen Daten über Pflegebedürftige enthalten.

---

## 11. Tests

```sh
ruff check .
pytest -q
node --check app/static/js/main.js
```

Zusätzlich gegen ein **echtes PostgreSQL** (nur eine Wegwerf-Datenbank, deren
Name „test“ enthält; die Tests arbeiten in einem eigenen, temporären Schema):

```sh
export AP5_TEST_POSTGRES_URL=postgresql+psycopg://pl2:PASSWORT@localhost:5432/pflegedb_test
pytest -q tests/test_mail_postgres.py
```

Was geprüft wird, unter anderem:

- Aufteilung in Teile (20 Adressen, Linklänge), nur BCC, Doppelte, Felder mit
  mehreren Adressen, ungültige Adressen
- ein Eintrag pro Klick, auch bei doppeltem Klick; veränderter oder
  gefälschter Token wird abgelehnt
- Filter der Historie: Jahr, Quartal und Monat (auch an den Grenzen wie
  31.03./01.04.), Bundesland, Suche, Versandstatus; Summe der Empfänger
- Versandbestätigung setzen und zurücksetzen, falsche Werte (422),
  unbekannte Einträge (404)
- Rollen: ohne passende Rolle kein Zugriff; die markierende Person wird
  gespeichert
- PostgreSQL 16: 8 gleichzeitig startende Worker, gleiches Schema aus
  SQL-Datei und App-Start, Update einer bestehenden Tabelle ohne Datenverlust,
  Prüfregeln der Datenbank

**Stand 28.11.2026:** ruff ohne Befund · 165 Tests bestanden, 14 übersprungen
(sie brauchen einen PostgreSQL-Server) · mit PostgreSQL 16 alle 14
übersprungenen Tests bestanden · Browser-Test der Versandhistorie mit 55
Einträgen (Filter, Details, Bestätigung, „Weitere laden“, Handy-Ansicht) ohne
Fehler.
Die E2E-Tests (siehe [e2e/README.md](../e2e/README.md)) laufen in GitHub
Actions bei jedem Pull Request, der die App ändert.

---

## 12. Grenzen und Ausblick

- **Echter Versand ist nicht automatisch feststellbar.** Das ist bei `mailto:`
  technisch so. Die Bestätigung von Hand kann vergessen werden; der Zähler
  „noch nicht bestätigt“ und der Filter „Noch offen“ helfen dabei.
- **Sehr große Auswahlen:** Ganz Deutschland ergibt rund 4.400 Adressen und
  damit über 200 einzelne E-Mails. Technisch korrekt, fachlich selten sinnvoll.
  Besser nach Bundesland oder Angebot filtern.
- **Kreis als Region:** Die Einrichtungsdaten haben kein Feld für den Kreis.
  Deshalb filtert die Historie nur nach Bundesland. Kommt der Kreis in die
  Daten, kann er genauso gespeichert und gefiltert werden.
- **Zeitgrenzen in UTC:** Monat und Quartal werden in UTC abgegrenzt. Eine
  Übergabe kurz nach Mitternacht deutscher Zeit am Monatsersten zählt noch
  zum Vormonat.
- **Löschfrist** für die Historie fehlt noch (Datenschutz, Team-Entscheidung).
- **Mailprogramme:** Weitere Tests mit Outlook, Thunderbird und Apple Mail
  sind sinnvoll, jeweils nur mit eigenen Test-Adressen.
- **Mögliche Erweiterung:** Versand über einen Mailserver der HFH mit echter
  Zustellbestätigung. Von Prof. Waage ausdrücklich nicht gefordert.

---

## 13. Glossar

| Begriff | Bedeutung |
|---|---|
| **BCC** | „Blindkopie“. Empfänger im BCC sehen die anderen Empfänger nicht. |
| **`mailto:`-Link** | Ein Link, der das Standard-Mailprogramm mit fertigen Empfängern, Betreff und Text öffnet. |
| **Mailprogramm** | Outlook, Thunderbird, Apple Mail oder ein anderes Programm, das auf dem eigenen Rechner E-Mails verschickt. |
| **Teil** | Eine E-Mail mit höchstens 20 Empfängern. Große Auswahlen bestehen aus mehreren Teilen. |
| **Übergabe** | Der Moment, in dem die App das Mailprogramm öffnet. Wird in der Historie gespeichert. |
| **Versandbestätigung** | Die nachträgliche Markierung „Versendet“ oder „Nicht versendet“ in der Versandhistorie. |
| **Token** | Ein signierter „Übergabe-Zettel“. Die Signatur zeigt, ob er verändert wurde. |
| **Migration** | Eine Änderung am Aufbau der Datenbank, hier das Anlegen der Tabelle oder neuer Spalten. |
| **Sperre (Advisory Lock)** | Eine PostgreSQL-Sperre, die dafür sorgt, dass immer nur ein Prozess gleichzeitig die Migration ausführt. |
| **Worker** | Einer von mehreren gleichzeitig laufenden App-Prozessen (Gunicorn). |
| **Rolle / Berechtigung** | Aus Keycloak: reader (Gruppe „Lesend“), editor („Redaktion“), admin („Admins“). Die Mail-Funktionen brauchen `read_centers`. |
| **422 / 404** | Antworten des Servers: 422 = Eingabe ungültig, 404 = Eintrag nicht gefunden. |
