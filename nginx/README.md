# nginx – der Empfang unseres Servers

Diese Seite erklärt in einfachen Worten, was nginx (gesprochen „Engine-X“) bei
PL2-HFH macht, wie er eingerichtet ist, wie certbot die HTTPS-Zertifikate
besorgt und worauf man beim Ändern achten muss. Technisches Vorwissen ist kaum
nötig.

## Inhalt

1. [nginx in einem Bild](#1-nginx-in-einem-bild)
2. [Wo nginx steht](#2-wo-nginx-steht)
3. [Der Weg einer Anfrage](#3-der-weg-einer-anfrage)
4. [Wer wohin geschickt wird](#4-wer-wohin-geschickt-wird)
5. [Die Dateien in diesem Ordner](#5-die-dateien-in-diesem-ordner)
6. [Wie nginx deployt wird](#6-wie-nginx-deployt-wird)
7. [certbot: der Ausweis-Erneuerer](#7-certbot-der-ausweis-erneuerer)
8. [Änderungen an der Konfiguration](#8-änderungen-an-der-konfiguration)
9. [Wenn etwas schiefgeht](#9-wenn-etwas-schiefgeht)
10. [Glossar](#10-glossar)

---

## 1. nginx in einem Bild

Stell dir unseren Server als **Bürogebäude** vor:

| Im Gebäude | Bei uns |
|---|---|
| 🚪 Es gibt **genau eine Eingangstür** nach draußen | nginx ist der einzige Container mit offenen Ports (80 und 443) |
| 🛎️ Am **Empfang** sitzt nginx | Jede Anfrage aus dem Internet kommt zuerst bei nginx an |
| ✉️ Besucher bringen **versiegelte Briefe** mit | Der Browser schickt verschlüsselte Daten (HTTPS) |
| 🔓 Der Empfang **öffnet das Siegel** und zeigt seinen Dienstausweis | nginx entschlüsselt die Verbindung mit dem Zertifikat (TLS) |
| 🪪 Der **Dienstausweis** muss alle paar Wochen erneuert werden | certbot holt ein neues Zertifikat bei Let's Encrypt (Abschnitt 7) |
| 🗺️ Der Empfang **schickt Besucher in die richtige Abteilung** | `/` geht zur App, `/idp/` geht zu Keycloak |
| 🚷 Die **Chef-Etage ist abgeschlossen** | `/idp/admin/` (Keycloak-Verwaltung) ist von außen gesperrt |
| 🧮 Der Empfang **zählt, wie oft jemand klingelt** | Rate-Limit: ca. 10 Anfragen pro Sekunde und IP-Adresse |
| ↪️ Wer durch die **Hintertür** (HTTP) oder den **Seiteneingang** (`www.`) kommt, wird zur Vordertür geschickt | Umleitung auf `https://projekthfh.tech` |
| 🙅 Wer nach einer **fremden Firma** fragt, bekommt keine Antwort | Unbekannte Hostnamen und Aufrufe per IP werden abgewiesen |

Die Abteilungen (App, Keycloak, Datenbanken) haben **keine eigene Tür nach
draußen**. Sie sind nur über den Empfang erreichbar. Fällt nginx aus, ist die
Seite von außen nicht erreichbar, obwohl die App selbst noch läuft.

---

## 2. Wo nginx steht

```
                    Internet (Browser)
                           │
                 Port 80 / 443 des Servers
                           │
┌──────────────────────────▼──────────────────────────────┐
│  Docker-Netzwerk "internal"                             │
│                                                         │
│   ┌─────────────┐   /       ┌────────────────────┐      │
│   │   nginx     │─────────► │ app (FastAPI)      │      │
│   │  Empfang,   │  :8000    │ Gunicorn + Uvicorn │──┐   │
│   │  TLS, Limit │           └────────────────────┘  │   │
│   │             │   /idp/   ┌────────────────────┐  │   │
│   │             │─────────► │ keycloak (Login)   │  │   │
│   └──────▲──────┘  :8080    └─────────┬──────────┘  │   │
│          │                            │             │   │
│          │                  ┌─────────▼──┐   ┌──────▼─┐ │
│          │                  │keycloak-db │   │ app-db │ │
│          │                  └────────────┘   └────────┘ │
└──────────┼──────────────────────────────────────────────┘
           │ liest nginx/certs/ und nginx/acme-challenge/
┌──────────┴──────────────────┐
│ certbot (auf dem Server,    │  ◄──── Let's Encrypt prüft per HTTP
│ nicht im Container)         │
└─────────────────────────────┘

Admin-Konsole von Keycloak: NICHT über nginx, sondern nur per SSH-Tunnel
auf 127.0.0.1:8080 (siehe keycloak/README.md).
```

---

## 3. Der Weg einer Anfrage

Was passiert, wenn jemand `https://projekthfh.tech/` aufruft:

1. **Adresse nachschlagen:** Der Browser fragt das DNS nach der IP-Adresse des Servers.
2. **Anklopfen:** Er verbindet sich mit Port 443. Dort wartet nginx.
3. **Ausweis zeigen:** nginx zeigt sein Zertifikat von Let's Encrypt. Der Browser
   prüft es und beide vereinbaren einen Schlüssel (TLS 1.2 oder 1.3).
4. **Klingel zählen:** nginx prüft das Rate-Limit für diese IP-Adresse.
   Zu viele Anfragen: Antwort **429** („zu viele Anfragen“).
5. **Abteilung suchen:** nginx vergleicht den Pfad mit seinen Regeln (`location`).
6. **Hausnummer nachschlagen:** nginx fragt den Docker-internen Namensdienst
   (`127.0.0.11`), welche interne IP der Container `app` gerade hat.
7. **Weiterreichen:** nginx gibt die Anfrage unverschlüsselt im internen Netz an
   die App weiter und legt einen Zettel bei: „Kam per HTTPS, von IP x.x.x.x,
   für Host projekthfh.tech“ (`X-Forwarded-*`-Header).
8. **Antwort zurück:** Die App antwortet. nginx ergänzt fehlende
   Sicherheits-Header, komprimiert Texte (gzip) und schickt alles verschlüsselt
   zurück.

> Warum der „Zettel“ wichtig ist: Ohne die `X-Forwarded-*`-Header würde die
> App denken, sie werde per `http://` aufgerufen, und Login-Links falsch bauen.
> Deshalb vertraut die App diesen Headern (`app/gunicorn_worker.py`).

---

## 4. Wer wohin geschickt wird

| Adresse | Ziel | Besonderheit |
|---|---|---|
| `http://…/.well-known/acme-challenge/…` | Ordner `nginx/acme-challenge/` | Nur für certbot / Let's Encrypt (Abschnitt 7) |
| `http://…` (alles andere) | – | Umleitung 301 auf `https://projekthfh.tech` |
| `https://www.projekthfh.tech/…` | – | Umleitung 301 auf `https://projekthfh.tech/…` |
| fremder Hostname / nackte IP | – | keine Antwort (Port 80: 444, Port 443: Handshake abgelehnt) |
| `/` und alles andere | App (`app:8000`) | Login wird von der App erzwungen |
| `/static/…` | App | Höheres Burst-Limit; mit `?v=` ein Jahr im Browser-Cache |
| `/healthz` | App | Kein Eintrag im Zugriffsprotokoll; Deploy und Container prüfen ihn |
| `/idp/admin/…` | – | Immer 404: Verwaltung ist von außen gesperrt |
| `/idp/…` | Keycloak (`keycloak:8080`) | Höheres Burst-Limit (100), weil die Login-Seite viele Dateien lädt |

nginx nimmt die **längste passende Regel**. `/idp/admin/` ist länger als
`/idp/` und gewinnt deshalb.

---

## 5. Die Dateien in diesem Ordner

```
nginx/
├── nginx.conf                Grundeinstellungen (Hausordnung)
├── conf.d/
│   ├── default.conf          Regeln für unsere Seite (Wegweiser am Empfang)
│   └── security-headers.inc  Sicherheits-Header, per include eingebunden
├── certs/                    Zertifikat + privater Schlüssel (NICHT im Git)
├── acme-challenge/           Ablage für certbot-Prüfdateien (NICHT im Git)
└── README.md                 diese Datei
```

### `nginx.conf` – die Hausordnung

| Einstellung | Bedeutung |
|---|---|
| `worker_processes auto` | So viele Arbeiter wie CPU-Kerne |
| `server_tokens off` | Die nginx-Version wird nicht verraten |
| `gzip …` | Texte (CSS, JavaScript, JSON, SVG) werden vor dem Versand gepackt |
| `limit_req_zone … rate=10r/s` | Das „Klingel-Zählwerk“: 10 Anfragen/s pro IP |
| `limit_req_status 429` | Wer zu oft klingelt, bekommt „429 zu viele Anfragen“ |
| `map $upstream_http_…` | Sicherheits-Header nur setzen, wenn die App keinen eigenen schickt |
| `map $arg_v …` | Cache-Regel für CSS/JS: mit Versionsnummer lange, sonst immer nachfragen |
| `map $host $canonical_host` | `www.projekthfh.tech` gilt als `projekthfh.tech` |

### `conf.d/default.conf` – der Wegweiser

Die Datei hat vier Blöcke (`server`), oben in der Datei kurz beschrieben:

1. **Port 80, bekannte Hosts:** certbot-Prüfdateien ausliefern, sonst auf HTTPS umleiten.
2. **Unbekannte Hosts:** abweisen, ohne das Zertifikat zu zeigen.
3. **Port 443, `www.`:** auf die Hauptadresse umleiten.
4. **Port 443, `projekthfh.tech` und `localhost`:** die eigentliche Anwendung.

| Einstellung | Bedeutung |
|---|---|
| `ssl_protocols TLSv1.2 TLSv1.3` | Alte, unsichere Verfahren (TLS 1.0/1.1) werden abgelehnt |
| `Strict-Transport-Security` | Browser merkt sich 2 Jahre: „Diese Seite nur noch per HTTPS“ |
| `limit_req … burst=20 nodelay` | Kurze Spitzen bis 20 Anfragen sind erlaubt, danach 429 |
| `resolver 127.0.0.11 valid=10s` | Container-Namen werden alle 10 s neu nachgeschlagen |
| `set $app_upstream app:8000` | Ziel als Variable, damit das Nachschlagen pro Anfrage passiert |

> **Warum die Variablen (`$app_upstream`)?** nginx merkt sich Container-Adressen
> sonst nur einmal beim Start. Wird die App neu gebaut, bekommt sie eine neue
> interne IP und nginx würde weiter an die alte Adresse schicken (Fehler 502).
> Außerdem startet nginx so auch, wenn Keycloak gar nicht läuft.

> **Warum `localhost` in `server_name`?** Der Deploy-Healthcheck und der
> Container-Healthcheck rufen `https://localhost/healthz` auf. Ohne diesen
> Eintrag würde nginx sie als „fremden Host“ abweisen.

**Sicherheits-Header:** Die App setzt sie selbst (`app/security.py`). nginx
ergänzt `X-Content-Type-Options`, `X-Frame-Options` und `Referrer-Policy` nur
dort, wo sie fehlen, zum Beispiel bei Umleitungen, 404 oder 502. Unter `/idp/`
setzt nginx bewusst kein `X-Frame-Options`, weil Keycloak das für einige Seiten
selbst regelt.

**Domain geändert?** Dann `server_name` in den Blöcken 1, 3 und 4 sowie die
`map $canonical_host` in `nginx.conf` anpassen.

---

## 6. Wie nginx deployt wird

nginx ist ein fertiges, offizielles Docker-Image (`nginx:1.31-alpine`). Wir
bauen es nicht selbst, sondern geben ihm nur unsere Konfiguration mit.

```
GitHub (Push oder PR)
   │
   ├─ Tests + "nginx -t" mit dem echten nginx-Image (fängt Tippfehler ab)
   │
   └─ nur bei Push auf main:
        App-Image bauen ──► Server per SSH
                              │
                              ├─ git reset --hard origin/main
                              ├─ prüfen: .env vollständig? certs/*.pem vorhanden?
                              ├─ docker compose --profile sso pull + up -d
                              ├─ nginx -t  ──► nginx -s reload   (neue Konfiguration live)
                              └─ Health check: https://localhost/healthz
```

Aus `docker-compose.yml`:

- **Ports:** nur nginx veröffentlicht `80:80` und `443:443`.
- **Ordner:** `nginx.conf`, `conf.d/`, `certs/` und `acme-challenge/` werden
  **nur lesbar** (`:ro`) in den Container eingebunden.
- **Start-Reihenfolge:** nginx startet erst, wenn die App „gesund“ ist.
- **Eigener Healthcheck:** alle 30 s `https://localhost/healthz` von innen.
  `docker compose ps` zeigt dann `healthy`.
- **Neustart:** `restart: unless-stopped`.
- **Logs:** pro Dienst höchstens 5 × 10 MB, danach werden alte gelöscht.

Zusätzlich prüft `.github/workflows/uptime.yml` jeden Morgen von außen, ob
`/healthz` antwortet und ob das Zertifikat noch mindestens 21 Tage gilt.

---

## 7. certbot: der Ausweis-Erneuerer

### Was certbot macht – im Bild

Das Zertifikat ist der **Dienstausweis des Servers**. Ausgestellt wird er von
der **Ausweisstelle Let's Encrypt**, kostenlos, aber nur für **90 Tage**.

certbot ist der **Bote**, der den Ausweis abholt und rechtzeitig erneuert:

1. 🙋 certbot sagt zu Let's Encrypt: „Ich hätte gern einen Ausweis für
   `projekthfh.tech` und `www.projekthfh.tech`.“
2. 🧩 Let's Encrypt antwortet: „Beweise, dass dir die Adresse gehört. Lege
   unter `http://projekthfh.tech/.well-known/acme-challenge/<code>` diesen
   Zettel ab.“
3. 📄 certbot legt den Zettel in den Ordner `nginx/acme-challenge/`. nginx
   liefert ihn unter genau dieser Adresse aus.
4. 🔎 Let's Encrypt ruft die Adresse aus dem Internet ab. Passt der Zettel,
   gibt es den neuen Ausweis.
5. 🗂️ certbot legt Zertifikat und Schlüssel unter
   `/etc/letsencrypt/live/projekthfh.tech/` ab.
6. 🔁 Der **Deploy-Hook** (`scripts/certbot-deploy-hook.sh`) kopiert beides
   nach `nginx/certs/` und lädt nginx neu. Ab jetzt zeigt der Empfang den
   neuen Ausweis.

Einmal installiert, prüft certbot **zweimal täglich** von selbst (systemd-Timer),
ob ein Zertifikat in weniger als 30 Tagen abläuft, und erneuert nur dann.

Diese Prüfmethode heißt **Webroot** (HTTP-01). Ihr Vorteil: nginx läuft
während der Prüfung einfach weiter.

### Wie es bei uns aufgesetzt ist

| Was | Wo |
|---|---|
| certbot selbst | direkt auf dem Ubuntu-Server (nicht als Container) |
| Einstellungen je Zertifikat | `/etc/letsencrypt/renewal/projekthfh.tech.conf` |
| Zertifikat und Schlüssel (Original) | `/etc/letsencrypt/live/projekthfh.tech/` (Verknüpfungen auf `archive/`) |
| Kopie, die nginx liest | `/opt/pl2-hfh/nginx/certs/fullchain.pem` und `privkey.pem` |
| Prüfzettel-Ordner (Webroot) | `/opt/pl2-hfh/nginx/acme-challenge/`, im Container `/var/www/certbot` |
| Deploy-Hook | `/etc/letsencrypt/renewal-hooks/deploy/pl2-hfh-nginx.sh` (Kopie von `scripts/certbot-deploy-hook.sh`) |
| Automatik | `certbot.timer` (apt) bzw. `snap.certbot.renew.timer` (snap) |
| Aktuelles Zertifikat | Let's Encrypt, für `projekthfh.tech` und `www.projekthfh.tech` |

> **Warum eine Kopie in `nginx/certs/`?** Die Dateien in `live/` sind nur
> Verknüpfungen auf `../../archive/…`. Bindet man nur `live/` in den Container
> ein, zeigen die Verknüpfungen dort ins Leere. Die Kopie hält außerdem den
> lokalen Aufbau (selbstsigniertes Zertifikat am selben Ort) gleich.

### Einrichtung auf dem Server (einmalig, nach dem Deploy dieses Standes)

Alle Befehle auf dem Server, als Benutzer mit `sudo`. Es werden keine Passwörter
gebraucht.

```bash
# 0) Ist-Stand ansehen: Methode (authenticator), Ablaufdatum, Timer, Hooks
sudo certbot certificates
sudo cat /etc/letsencrypt/renewal/projekthfh.tech.conf
systemctl list-timers | grep -i certbot
sudo ls /etc/letsencrypt/renewal-hooks/*/

# 1) Prüfzettel-Weg testen: nginx muss die Datei über HTTP ausliefern
sudo mkdir -p /opt/pl2-hfh/nginx/acme-challenge/.well-known/acme-challenge
echo ok | sudo tee /opt/pl2-hfh/nginx/acme-challenge/.well-known/acme-challenge/ping
curl http://projekthfh.tech/.well-known/acme-challenge/ping      # erwartet: ok
sudo rm /opt/pl2-hfh/nginx/acme-challenge/.well-known/acme-challenge/ping

# 2) certbot auf die Webroot-Methode umstellen (macht selbst einen Probelauf)
sudo certbot reconfigure --cert-name projekthfh.tech \
  --webroot --webroot-path /opt/pl2-hfh/nginx/acme-challenge

# 3) Deploy-Hook installieren
sudo install -m 755 /opt/pl2-hfh/scripts/certbot-deploy-hook.sh \
  /etc/letsencrypt/renewal-hooks/deploy/pl2-hfh-nginx.sh

# 4) Probelauf der ganzen Verlängerung (gegen die Test-Ausweisstelle)
sudo certbot renew --dry-run
```

Falls in Schritt 0 unter `renewal-hooks/pre/` oder `post/` Skripte liegen, die
nginx stoppen und wieder starten (typisch für die alte Methode `standalone`),
können sie nach erfolgreichem Schritt 4 entfernt werden.

Das Hook-Skript läuft nur nach einer echten Erneuerung. Wer es sofort testen
will, kann eine Erneuerung erzwingen. Das zählt gegen die Mengengrenzen von
Let's Encrypt, deshalb sparsam nutzen:

```bash
sudo certbot renew --cert-name projekthfh.tech --force-renewal
```

### Worauf man bei certbot achten muss

| Punkt | Warum |
|---|---|
| **Port 80 muss offen bleiben** | Let's Encrypt prüft über HTTP. Firewall-Regel für 80 nicht schließen, auch wenn „alles HTTPS“ ist |
| **Die Prüf-Route muss vor der HTTPS-Umleitung stehen** | Sie steht in `default.conf`, Block 1. Beim Umbau nicht entfernen |
| **DNS beider Namen muss auf den Server zeigen** | Das Zertifikat gilt für `projekthfh.tech` und `www.`. Zeigt ein Name woanders hin, scheitert die ganze Erneuerung |
| **Ohne Reload kein neuer Ausweis** | certbot ändert nur Dateien. Der Deploy-Hook lädt nginx neu, ohne ihn läuft das alte Zertifikat ab |
| **Mengengrenzen von Let's Encrypt** | z. B. höchstens 5 identische Zertifikate pro Woche. Zum Ausprobieren immer `--dry-run` nutzen |
| **Keine Ablauf-E-Mails mehr** | Let's Encrypt verschickt seit 2025 keine Erinnerungen. Deshalb der tägliche Check in `uptime.yml` |
| **Laufzeiten werden kürzer** | Let's Encrypt hat angekündigt, die Gültigkeit schrittweise zu verkürzen. Umso wichtiger ist die Automatik |
| **Privater Schlüssel bleibt geheim** | `privkey.pem` nie ins Git, in Chats oder Tickets. Rechte `600` |
| **`/etc/letsencrypt` sichern** | Enthält Konto-Schlüssel und Einstellungen. Gehört ins Server-Backup |
| **Nur ein certbot** | Nicht gleichzeitig per apt und snap installieren, sonst laufen zwei Timer mit verschiedenen Einstellungen |

### Ablaufdatum prüfen

```bash
echo | openssl s_client -connect projekthfh.tech:443 -servername projekthfh.tech 2>/dev/null \
  | openssl x509 -noout -enddate
```

### Lokal

Lokal gibt es kein Let's Encrypt. `./scripts/generate_dev_cert.sh` erzeugt ein
selbstsigniertes Zertifikat in `nginx/certs/`. Die Browser-Warnung ist dabei
normal.

---

## 8. Änderungen an der Konfiguration

Seit diesem Stand lädt **jeder Deploy nginx automatisch neu**, nachdem er die
Konfiguration mit `nginx -t` geprüft hat. Schon im PR prüft die CI die
Konfiguration mit dem echten nginx-Image.

Von Hand (z. B. nach einer Änderung direkt auf dem Server):

```bash
cd /opt/pl2-hfh
docker compose exec nginx nginx -t          # 1) Generalprobe
docker compose exec nginx nginx -s reload   # 2) ohne Unterbrechung neu laden
```

Bei einem Tippfehler meldet Schritt 1 den Fehler, und die alte Konfiguration
läuft unverändert weiter.

Lokal testen:

```bash
./scripts/generate_dev_cert.sh
docker compose up -d
curl -k https://localhost/healthz      # erwartet: {"status":"ok"}
```

---

## 9. Wenn etwas schiefgeht

| Anzeige | Bedeutung | Was tun |
|---|---|---|
| Seite lädt gar nicht | nginx läuft nicht oder Ports zu | `docker compose ps`, `docker compose logs nginx` |
| **502 Bad Gateway** | nginx erreicht die App/Keycloak nicht | `docker compose ps`: läuft `app` bzw. `keycloak`? Logs der Abteilung prüfen |
| **429** bei vielen Klicks | Rate-Limit hat gegriffen | Kurz warten. Tritt es bei normaler Nutzung auf, Limit prüfen |
| **404** unter `/idp/admin/` | gewollt | Admin-Konsole nur per SSH-Tunnel |
| Keine Antwort per IP-Adresse | gewollt | Immer über `https://projekthfh.tech` aufrufen |
| Zertifikatswarnung im Browser | Zertifikat abgelaufen oder Test-Zertifikat | `sudo certbot certificates`, dann `sudo certbot renew --dry-run` |
| `uptime.yml` meldet „Zertifikat läuft ab“ | Erneuerung klappt seit über einer Woche nicht | `sudo journalctl -u certbot` bzw. `/var/log/letsencrypt/letsencrypt.log` |
| certbot: „Timeout during connect“ / 404 bei der Prüfung | Port 80 zu oder Prüf-Route fehlt | Schritt 1 der Einrichtung wiederholen |
| Deploy bricht bei `nginx -t` ab | Fehler in `nginx/` | Fehlermeldung im Actions-Log lesen; alte Konfiguration läuft weiter |
| Deploy bricht ab: „certs fehlt“ | `nginx/certs/*.pem` fehlt auf dem Server | Hook-Skript erneut ausführen lassen (`--force-renewal`) oder Dateien kopieren |

Nützliche Befehle auf dem Server:

```bash
docker compose logs --tail=100 nginx        # letzte Meldungen
docker compose exec nginx nginx -T | less   # gesamte geladene Konfiguration
```

---

## 10. Glossar

| Begriff | Erklärung |
|---|---|
| **Reverse Proxy** | Ein Vermittler vor den eigentlichen Diensten, der Anfragen entgegennimmt und weitergibt |
| **TLS / HTTPS** | Verschlüsselung zwischen Browser und Server |
| **TLS-Terminierung** | Die Verschlüsselung endet bei nginx; dahinter wird intern unverschlüsselt gesprochen |
| **Zertifikat** | Digitaler Ausweis des Servers, ausgestellt von einer vertrauenswürdigen Stelle |
| **Let's Encrypt** | Kostenlose Stelle, die Zertifikate für 90 Tage ausstellt |
| **certbot** | Programm, das Zertifikate bei Let's Encrypt beantragt und erneuert |
| **ACME / HTTP-01** | Das Verfahren, mit dem Let's Encrypt prüft, ob die Domain uns gehört |
| **Webroot** | certbot legt den Prüfzettel in einen Ordner, den der laufende Webserver ausliefert |
| **Deploy-Hook** | Skript, das certbot nach einer erfolgreichen Erneuerung ausführt |
| **HSTS** | Anweisung an den Browser, die Seite nur noch per HTTPS aufzurufen |
| **HTTP/2** | Neuere HTTP-Version, die mehrere Dateien über eine Verbindung lädt |
| **Rate-Limit** | Obergrenze für Anfragen pro Zeit und IP-Adresse |
| **location** | Eine Regel in nginx: „Für diesen Pfad mach Folgendes“ |
| **upstream** | Der Dienst hinter nginx, an den weitergereicht wird |
| **502 Bad Gateway** | nginx lebt, aber der Dienst dahinter antwortet nicht |
| **429 Too Many Requests** | Das Rate-Limit hat gegriffen |
| **gzip** | Verfahren zum Packen von Text, damit weniger Daten übertragen werden |
