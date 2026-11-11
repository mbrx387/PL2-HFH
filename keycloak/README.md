# Keycloak – die Ausweisbehörde unserer App

Dieses Dokument erklärt, was Keycloak ist, wie es funktioniert und wie wir es
im Pflegezentren-Finder einsetzen. Es richtet sich ausdrücklich auch an
Leserinnen und Leser **ohne** technischen Hintergrund. Fachbegriffe werden
beim ersten Auftauchen erklärt und stehen gesammelt im [Glossar](#11-glossar).

---

## 1. Keycloak in einem Bild

Stell dir vor, unsere App ist ein **Gebäude mit Pförtner**.

- Der Pförtner kennt keine Passwörter. Er lässt nur Menschen hinein, die einen
  **gültigen, gestempelten Ausweis** vorzeigen.
- Ausweise stellt eine eigene **Ausweisbehörde** aus: **Keycloak**. Dort sind
  alle Personen registriert, dort wird das Passwort geprüft, dort wird der
  Ausweis gestempelt.
- Wer ohne Ausweis kommt, wird vom Pförtner freundlich zur Behörde geschickt
  und kommt mit Ausweis zurück.

```mermaid
flowchart LR
    P([👤 Person]) -->|1. möchte rein| A[🏢 App<br/>mit Pförtner]
    A -->|2. „Kein Ausweis? Bitte zur Behörde.“| K[🏛️ Keycloak<br/>Ausweisbehörde]
    K -->|3. prüft Passwort<br/>und stellt Ausweis aus| P
    P -->|4. zeigt Ausweis| A
    A -->|5. lässt hinein| L[📋 Liste der<br/>Pflegestellen]
```

**Warum dieser Umweg?** Passwörter sicher speichern, Konten nach zu vielen
Fehlversuchen sperren, Zwei-Faktor-Anmeldung, Passwort zurücksetzen: Genau an
diesen Stellen entstehen sonst die meisten Sicherheitslücken. Keycloak ist eine
bewährte, kostenlose Open-Source-Software, die das alles fertig mitbringt. Unsere
App muss deshalb **keine einzige Zeile** Passwort-Logik enthalten.

---

## 2. Das Bildwörterbuch

Die Admin-Konsole von Keycloak benutzt englische Fachbegriffe. So lassen sie
sich übersetzen:

| Begriff in Keycloak | Im Bild | Bei uns |
|---|---|---|
| **Realm** | Eine eigenständige Behörde mit eigenen Akten und Regeln | `hfh-pflege` (für die App) und `master` (nur zum Verwalten von Keycloak) |
| **Client** | Ein Gebäude, das die Ausweise dieser Behörde akzeptiert | `pflege-finder` = unsere App |
| **User** (Benutzer) | Eine registrierte Person | jede Mitarbeiterin, jeder Mitarbeiter |
| **Group** (Gruppe) | Eine Abteilung; alle Mitglieder bekommen dieselben Rechte | `Lesend`, `Redaktion`, `Admins` |
| **Role** (Rolle) | Eine Zugangsberechtigung, die auf dem Ausweis steht | `reader`, `editor`, `admin` |
| **Token** | Der gestempelte Ausweis selbst | wird nach jedem Login ausgestellt |
| **Session** (Sitzung) | Wie lange der Ausweis gilt | höchstens 8 Stunden |
| **Identity Provider** | Eine Partnerbehörde, deren Ausweise anerkannt werden | geplant: Login mit HFH-Konto (Issue #52) |

---

## 3. Wie die Behörde aufgebaut ist

```mermaid
flowchart TB
    subgraph KC["🏛️ Keycloak-Server"]
        direction TB
        subgraph M["Realm „master“ – das Ministerium"]
            ADM["🔑 Admin-Konto<br/>darf alles in Keycloak"]
        end
        subgraph H["Realm „hfh-pflege“ – unsere Behörde"]
            direction LR
            U["👤 Benutzer"] -->|ist Mitglied| G["👥 Gruppe<br/>Lesend · Redaktion · Admins"]
            G -->|trägt| R["🎫 Rolle<br/>reader · editor · admin"]
            R -->|gilt für| C["🏢 Client<br/>pflege-finder"]
        end
        ADM -.->|verwaltet| H
    end
    DB[("🗄️ keycloak-db<br/>das Aktenarchiv")]
    KC --- DB
```

- **Der Realm `master`** ist nur für die Verwaltung da. Dort gehören **keine**
  normalen Nutzerinnen und Nutzer hinein.
- **Der Realm `hfh-pflege`** ist die Behörde für unsere App. Hier liegen alle
  Konten, Gruppen und Regeln.
- **Rechte werden über Gruppen vergeben**, nicht an jede Person einzeln. Neue
  Kolleginnen und Kollegen kommen einfach in die passende Gruppe.
- **Alles wird dauerhaft in einer eigenen Datenbank** (`keycloak-db`)
  gespeichert, getrennt von den Daten der Pflegestellen.

---

## 4. Die drei Ausweise (Tokens)

Nach einem erfolgreichen Login stellt Keycloak drei digital unterschriebene
Dokumente aus. Die Unterschrift kann niemand fälschen: Die App erkennt sofort,
ob ein Ausweis wirklich von unserer Behörde stammt.

| | Ausweis | Frage, die er beantwortet | Gültigkeit |
|---|---|---|---|
| 🪪 | **ID-Token** | „Wer bist du?“ (Name, E-Mail) | einmalig beim Login |
| 🎟️ | **Access-Token** | „Was darfst du?“ (Rollen) | 5 Minuten |
| 🔄 | **Refresh-Token** | „Bitte verlängern“, ohne erneutes Passwort | so lange wie die Sitzung |

Unsere App liest Name, E-Mail und Rollen aus und merkt sie sich in einem
signierten Cookie für höchstens 8 Stunden.

---

## 5. Der Login Schritt für Schritt

```mermaid
sequenceDiagram
    autonumber
    actor P as 👤 Person
    participant A as 🏢 App
    participant K as 🏛️ Keycloak
    P->>A: Seite aufrufen
    A-->>P: Kein Ausweis – bitte zu Keycloak
    P->>K: Benutzername + Passwort (+ Einmalcode)
    K-->>P: Abholschein (Einmal-Code)
    P->>A: Abholschein abgeben
    A->>K: Abholschein + Geheimnis der App eintauschen
    K-->>A: Ausweise (Tokens)
    A-->>P: Willkommen – die Liste wird angezeigt
```

Das Besondere an diesem Ablauf:

- **Das Passwort sieht nur Keycloak**, niemals die App.
- Der Browser bekommt nur einen **wertlosen Abholschein**. Den echten Ausweis
  holt die App selbst ab, direkt bei Keycloak und mit einem nur ihr bekannten
  Geheimnis (dem *Client-Secret*).
- Zusätzlich sendet die App bei jedem Login ein Einmal-Geheimnis mit (**PKCE**).
  Selbst ein abgefangener Abholschein ist damit nutzlos.

---

## 6. Wer darf was? Rollen und Gruppen

| Gruppe | Rolle auf dem Ausweis | Darf in der App |
|---|---|---|
| **Lesend** | `reader` | Liste ansehen, filtern, Sammel-Mail öffnen |
| **Redaktion** | `editor` | zusätzlich Stellen anlegen, ändern, deaktivieren |
| **Admins** | `admin` | dieselben Rechte wie Redaktion |

Wichtig:

- Wer in **keiner** Gruppe ist, kann sich zwar anmelden, sieht aber keine Daten
  (die App antwortet mit „keine Berechtigung“).
- Die Rolle `admin` in der App ist **nicht** dasselbe wie ein Admin-Konto in
  Keycloak. Sie gibt keinerlei Rechte in der Keycloak-Verwaltung.
- Ändert sich die Gruppe einer Person, wirkt das erst nach erneutem Anmelden.

---

## 7. Die Schutzmechanismen

Diese Regeln gelten im Realm `hfh-pflege`:

| Schutz | Was er tut | Bild |
|---|---|---|
| **Sperre nach Fehlversuchen** | Nach 5 falschen Passwörtern wird das Konto vorübergehend gesperrt, mit wachsender Wartezeit (max. 15 Minuten) | Der Schalter schließt nach zu vielen Fehlversuchen |
| **Passwort-Regeln** | Mindestens 12 Zeichen, nicht der Benutzername, nicht die E-Mail, keins der letzten 3 Passwörter | Keine Schlüssel, die jeder nachmachen kann |
| **Einmalcode (Zwei-Faktor)** | Neue Konten richten beim ersten Login eine Authenticator-App ein | Ein zweites Schloss: Passwort allein reicht nicht |
| **Begrenzte Sitzungen** | Nach 30 Minuten Untätigkeit oder spätestens 8 Stunden ist eine neue Anmeldung nötig | Der Ausweis läuft ab |
| **Audit-Protokoll** | Anmeldungen, Fehlversuche und Admin-Änderungen werden 30 Tage gespeichert | Das Besucherbuch der Behörde |
| **Keine Selbstregistrierung** | Konten legt nur ein Admin an | Kein Ausweis ohne Antrag |
| **Verwaltung nur über Tunnel** | Die Admin-Konsole ist aus dem Internet nicht erreichbar | Das Ministerium hat keinen Publikumseingang |

„Passwort vergessen“ ist bewusst ausgeschaltet, solange kein E-Mail-Versand
eingerichtet ist (Issue #53). Bis dahin setzt ein Admin das Passwort zurück.

---

## 8. Wie Keycloak bei uns läuft

```mermaid
flowchart LR
    B([🌐 Browser]) -->|HTTPS| N[🚪 nginx<br/>Türsteher]
    N -->|/idp/| K[🏛️ Keycloak]
    N -->|alles andere| A[🏢 App]
    A -.->|Ausweise abholen,<br/>intern| K
    K --- D[(🗄️ keycloak-db)]
    T([💻 Admin-Laptop]) -->|SSH-Tunnel| K
    N -.-x|/idp/admin/ gesperrt| K
```

- Keycloak läuft als eigener Container neben der App, erreichbar unter
  `https://projekthfh.tech/idp/`.
- Davor steht **nginx**: Er verschlüsselt die Verbindung (HTTPS) und sperrt den
  Verwaltungsbereich nach außen.
- Die **Admin-Konsole** erreicht man nur über einen SSH-Tunnel:

  ```bash
  ssh -L 8080:localhost:8080 <benutzer>@<server>
  # dann im Browser: http://localhost:8080/idp/admin/
  ```

---

## 9. Die wichtigste Regel: „nur beim allerersten Start“

In diesem Ordner liegen zwei Dateien, die dieselben Einstellungen beschreiben:

| Datei | Wann sie wirkt |
|---|---|
| `realm-export.json` | **Nur beim allerersten Start**, wenn die Keycloak-Datenbank noch leer ist. Danach wird sie ignoriert. |
| `configure.sh` | Jederzeit. Überträgt die Einstellungen auf eine **bestehende** Keycloak-Installation und kann beliebig oft laufen. |

Im Bild: Die Realm-Datei ist das **Gründungsdokument** der Behörde. Ist die
Behörde einmal gegründet, ändert ein neues Gründungsdokument nichts mehr.
Änderungen laufen danach über die Verwaltung (Admin-Konsole) oder das Skript.

```bash
cd /opt/pl2-hfh
./keycloak/configure.sh                 # fragt das Admin-Passwort ab
```

Ebenfalls nur beim ersten Start übernommen: das Admin-Passwort und das
Datenbank-Passwort aus der `.env`. Werden sie später in der `.env` geändert,
ändert sich in Keycloak **nichts**, und Keycloak findet im schlimmsten Fall
seine eigene Datenbank nicht mehr.

**Nie im Repository:** Passwörter, das Client-Secret und echte Benutzerkonten.

---

## 10. Häufige Aufgaben in der Admin-Konsole

Alle Wege beziehen sich auf den Realm **`hfh-pflege`** (oben links auswählen).

| Aufgabe | Weg |
|---|---|
| **Person anlegen** | *Users → Add user* → Benutzername, E-Mail, Name → *Create* → *Credentials → Set password* (Haken „Temporary“ an) |
| **Rechte vergeben** | *Users → Person → Groups → Join group* → `Lesend`, `Redaktion` oder `Admins` |
| **Passwort zurücksetzen** | *Users → Person → Credentials → Reset password* (Haken „Temporary“ an) |
| **Konto sperren** | *Users → Person* → Schalter *Enabled* aus |
| **Handy mit Authenticator verloren** | *Users → Person → Credentials* → Eintrag „OTP“ löschen; beim nächsten Login wird neu eingerichtet |
| **Gesperrtes Konto nach Fehlversuchen entsperren** | *Users → Person* → Hinweis „temporarily locked“ → entsperren |
| **Wer hat sich wann angemeldet?** | *Events → User events* |
| **Wer hat was geändert?** | *Events → Admin events* |

---

## 11. Glossar

| Begriff | Erklärung |
|---|---|
| **Admin-Konsole** | Die Verwaltungsoberfläche von Keycloak im Browser |
| **Audit / Events** | Protokoll von Anmeldungen und Änderungen |
| **Brute-Force-Schutz** | Sperre gegen massenhaftes Passwort-Raten |
| **Claim** | Ein einzelner Eintrag auf dem Ausweis, z. B. `email` oder `roles` |
| **Client** | Eine Anwendung, die Keycloak-Logins nutzt (bei uns `pflege-finder`) |
| **Client-Secret** | Das Passwort der App gegenüber Keycloak |
| **Identity Provider** | Ein fremder Login-Dienst, dem Keycloak vertraut (z. B. Microsoft-Konto der HFH) |
| **MFA / OTP** | Mehr-Faktor-Anmeldung; OTP ist ein 6-stelliger Einmalcode aus einer App |
| **OpenID Connect (OIDC)** | Der Standard, nach dem App und Keycloak miteinander sprechen |
| **PKCE** | Ein Einmal-Geheimnis pro Login, das abgefangene Codes wertlos macht |
| **Realm** | Ein abgeschlossener Bereich mit eigenen Benutzern und Regeln |
| **Required Action** | Eine Aufgabe, die beim nächsten Login erzwungen wird (z. B. Passwort ändern) |
| **Session** | Die Zeitspanne, in der man angemeldet bleibt |
| **SSO (Single Sign-On)** | Einmal anmelden, in mehreren Anwendungen eingeloggt sein |
| **Token** | Ein digital unterschriebener Ausweis |

---

## 12. Weiterführend

- Offizielle Dokumentation: <https://www.keycloak.org/documentation>
