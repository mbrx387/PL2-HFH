# Betrieb: INT und PROD

Es gibt zwei Server mit genau demselben Aufbau (Docker Compose, nginx,
Keycloak, certbot):

| | **INT** | **PROD** |
|---|---|---|
| Server | bisheriger self-hosted Linux-Server | Server der HFH |
| Adresse | `https://projekthfh.tech` | HFH-Domain (unten `DOMAIN_PROD`) |
| Bekommt | jeden PR **und** jeden Merge nach `main` | nur Merges nach `main` |
| Daten | Testdaten und Testnutzer | echte Daten und Nutzer |
| GitHub-Environment | `INT` | `PROD` (nur Branch `main`) |

```
PR öffnen / pushen
   └─ test ─► Image sha-<PR-Commit> ─► deploy-int  (INT zeigt den PR)
                                          │
              Merge-Button nur bei grünem deploy-int (Ruleset auf main)
                                          ▼
Merge nach main
   └─ test ─► Image sha-<main-Commit> ─► deploy-int ─► deploy-prod
                                          (INT = main)  (PROD = main)
```

Der Merge ist die Freigabe. Eine zusätzliche Klick-Freigabe gibt es nicht.
`deploy-prod` läuft nur, wenn `deploy-int` mit **demselben** Commit grün war.

---

## Namen

Alles Bestehende behält seinen Namen und gilt für INT. Neues für PROD endet auf
`_PROD`. GitHub erlaubt in Secret- und Variablennamen keinen Bindestrich. Linux
lehnt Großbuchstaben in Benutzernamen ab, deshalb dort `-prod`.

| INT (unverändert) | PROD (neu) | Wo |
|---|---|---|
| Secret `SSH_HOST` | Secret `SSH_HOST_PROD` | GitHub → Environment `PROD` |
| Secret `SSH_USER` | Secret `SSH_USER_PROD` | GitHub → Environment `PROD` |
| Secret `SSH_PRIVATE_KEY` | Secret `SSH_PRIVATE_KEY_PROD` | GitHub → Environment `PROD` |
| Variable `PUBLIC_HOST` | Variable `PUBLIC_HOST_PROD` | GitHub → Repository-Variablen |
| Deploy-User `<SSH_USER>` | Deploy-User `<SSH_USER>-prod` | HFH-Server |
| Secret `ZQP_API_URL` | – (ETL läuft in GitHub) | GitHub |
| `/opt/pl2-hfh`, `.env`-Schlüssel | gleich, eigene Werte | Server |

**PROD wird über `PUBLIC_HOST_PROD` eingeschaltet.** Solange diese Variable
fehlt, überspringen `deploy-prod`, der PROD-Teil von `uptime.yml` und der
PROD-Import in `GetDataFromAPI.yml` ihre Arbeit. Erst setzen, wenn Phase 1 bis 3
erledigt sind.

---

## Phase 1: HFH-Server prüfen (nur lesen)

Erst wenn alle Punkte erfüllt sind, geht es mit Phase 2 weiter.

**Mit der HFH-IT klären**
- [ ] Wer hat root, wer ist Ansprechperson? Gibt es Wartungsfenster und Patch-Vorgaben?
- [ ] Sichert die HFH den Server, oder sichern wir selbst?
- [ ] Datenschutz: In Keycloak liegen personenbezogene Daten (Namen, E-Mail).
      Verfahrensverzeichnis und Zuständigkeit klären.
- [ ] Ist Let's Encrypt erlaubt, oder sind HFH-Zertifikate Pflicht (z. B. DFN/HARICA)?
- [ ] Wer legt den DNS-Eintrag `DOMAIN_PROD` an?

**System**
```bash
cat /etc/os-release; uname -m             # Debian/Ubuntu, x86_64 (Image gibt es nur für amd64)
nproc; free -h; df -h /opt /var/lib/docker # Richtwert: ≥ 2 vCPU, ≥ 4 GB RAM, ≥ 20 GB frei
timedatectl                                # "NTP service: active" (wichtig für TLS und Login-Token)
sudo ss -tlnp                              # 80 und 443 dürfen nicht belegt sein
docker --version 2>/dev/null; systemctl list-units --type=service --state=running
env | grep -i proxy                        # Muss ein Proxy benutzt werden?
```

**Netz von außen** (vom Laptop)
```bash
nc -vz <host> 22; nc -vz <host> 80; nc -vz <host> 443
```
- [ ] SSH ist auch **aus GitHub Actions** erreichbar. Die Runner-IP-Bereiche
      sind groß und wechseln, eine Allowlist reicht dafür nicht. Test: einmal
      einen Workflow mit `ssh-keyscan <host>` laufen lassen.

**Netz nach außen** (vom Server)
```bash
curl -sI https://ghcr.io | head -1
curl -sI https://github.com | head -1
curl -s  https://acme-v02.api.letsencrypt.org/directory | head -3
curl -sI https://download.docker.com | head -1
```

**DNS und SSH**
```bash
dig +short <DOMAIN_PROD>; dig CAA <HFH-Domain>     # CAA leer oder mit letsencrypt.org
sudo sshd -T | grep -Ei 'passwordauthentication|permitrootlogin|^port|allowusers|allowgroups'
```

## Phase 2: Grundvoraussetzungen (einmalig, als root)

```bash
# 1) System
apt update && apt full-upgrade -y
apt install -y unattended-upgrades git curl python3 ca-certificates
timedatectl set-timezone Europe/Berlin

# 2) Docker Engine + Compose-Plugin aus dem offiziellen Docker-Repo
#    (Anleitung: https://docs.docker.com/engine/install/). Dieselbe
#    Major-Version wie auf INT (dort: docker version).
systemctl enable --now docker
docker run --rm hello-world

# 3) Deployment-User-PROD (die docker-Gruppe ist root-gleich: nur dieser User)
useradd -m -s /bin/bash <SSH_USER>-prod
usermod -aG docker <SSH_USER>-prod
install -d -m 700 -o <SSH_USER>-prod -g <SSH_USER>-prod /home/<SSH_USER>-prod/.ssh
install -d -o <SSH_USER>-prod -g <SSH_USER>-prod /opt/pl2-hfh

# 4) certbot (dieselbe Variante wie auf INT: apt)
apt install -y certbot
```

**SSH-Schlüssel nur für PROD.** Er wird auf dem eigenen Rechner erzeugt, nicht
der INT-Schlüssel:
```bash
ssh-keygen -t ed25519 -C "github-actions-prod" -f ./deploy_prod -N ""
```
- `deploy_prod.pub` kommt auf dem Server nach
  `/home/<SSH_USER>-prod/.ssh/authorized_keys` (Rechte `600`, Besitzer der User).
- Den Inhalt von `deploy_prod` trägst du selbst in GitHub als
  `SSH_PRIVATE_KEY_PROD` ein. Danach die lokale Datei löschen.

**Härten**
- [ ] `/etc/ssh/sshd_config`: `PasswordAuthentication no`, `PermitRootLogin no`.
      Admins mit persönlichem Account und Schlüssel.
- [ ] Firewall (ufw oder HFH-Vorgabe): eingehend nur 22, 80, 443.
      Keycloak-Admin (8080) ist ohnehin nur an `127.0.0.1` gebunden.

## Phase 3: Applikation

### 3.1 GitHub (Settings)
- [ ] **Environments:** `INT` ohne Regeln. Bei `PROD` unter „Deployment
      branches“ nur `main` zulassen.
- [ ] **Environment `PROD` → Secrets:** `SSH_HOST_PROD`, `SSH_USER_PROD`,
      `SSH_PRIVATE_KEY_PROD`.
- [ ] **Bestehendes nicht anfassen:** `SSH_HOST`, `SSH_USER`, `SSH_PRIVATE_KEY`,
      `PUBLIC_HOST`, `ZQP_API_URL`.
- [ ] **Ruleset für `main`:** PR erforderlich. Required status checks
      `test` und `deploy-int / deploy`. „Require branches to be up to date before
      merging“ aktivieren, damit der auf INT getestete Stand genau der ist, der
      nach `main` kommt.
- [ ] **Dependabot:** Dependabot-PRs bekommen keine normalen Secrets, und
      `deploy-int` würde scheitern. Deshalb `SSH_HOST`, `SSH_USER` und
      `SSH_PRIVATE_KEY` zusätzlich unter *Settings → Secrets → Dependabot* anlegen.
- [ ] **Variable `PUBLIC_HOST_PROD`** erst ganz am Ende setzen (Abschnitt 3.4).

### 3.2 PROD-`.env`
`/opt/pl2-hfh/.env` aus `.env.example` anlegen (Besitzer `<SSH_USER>-prod`,
Rechte `600`). Alle Secrets **neu** erzeugen (`openssl rand -base64 32`), keine
Werte von INT übernehmen. Die Werte trägst nur du ein.

| Schlüssel | PROD-Wert |
|---|---|
| `APP_PUBLIC_URL` | `https://<DOMAIN_PROD>`, daraus entsteht `PUBLIC_HOST` automatisch |
| `ALLOWED_ORIGINS` | `https://<DOMAIN_PROD>` |
| `KC_HOSTNAME` | `https://<DOMAIN_PROD>/idp` |
| `OIDC_ISSUER` | `https://<DOMAIN_PROD>/idp/realms/hfh-pflege` |
| `SECRET_KEY`, `APP_DB_PASSWORD`, `KEYCLOAK_DB_PASSWORD`, `KEYCLOAK_ADMIN_PASSWORD` | neu |
| `OIDC_CLIENT_SECRET` | nach dem Realm-Import aus Keycloak (README, Abschnitt 8) |

### 3.3 Zertifikat, Keycloak, Daten
1. **Repo und Übergangszertifikat** (als `<SSH_USER>-prod`):
   ```bash
   cd /opt/pl2-hfh
   git init -b main && git remote add origin https://github.com/mbrx387/PL2-HFH.git
   git fetch origin main && git checkout -f main
   ./scripts/generate_dev_cert.sh
   ```
2. **certbot** wie in [`nginx/README.md`](../nginx/README.md), Abschnitt 7
   („Einrichtung auf einem neuen Server“), mit `--cert-name <DOMAIN_PROD>`.
   Danach `certbot renew --dry-run`.
3. **Keycloak:** Inbetriebnahme wie im README, Abschnitt 8. Redirect-URIs und
   Web-Origins des Clients `pflege-finder` auf `https://<DOMAIN_PROD>`.
   Master-Realm mit persönlichen Admins und OTP.
4. **Datenumzug (einmalig):** Wenn die echten Daten heute auf INT liegen:
   ```bash
   # INT
   docker compose exec -T app-db      pg_dump -U pl2 -Fc pflegedb > app.dump
   docker compose exec -T keycloak-db pg_dump -U keycloak -Fc keycloak > kc.dump
   # per scp auf PROD kopieren, VOR dem ersten Keycloak-Start einspielen:
   docker compose up -d app-db keycloak-db
   docker compose exec -T app-db      pg_restore -U pl2 -d pflegedb --clean --if-exists < app.dump
   docker compose exec -T keycloak-db pg_restore -U keycloak -d keycloak --clean --if-exists < kc.dump
   ```
   Danach die Dumps auf beiden Servern löschen. Anschließend auf INT die echten
   Nutzer durch Testnutzer ersetzen, denn auf INT läuft ungeprüfter PR-Code.
5. **Backup:** `backup.sh` liegt bisher nur auf INT. Ohne Secrets ins Repo
   holen, auf PROD per Cron täglich ausführen und eine Kopie außerhalb des
   Servers ablegen.

### 3.4 Einschalten
1. Variable **`PUBLIC_HOST_PROD`** = `<DOMAIN_PROD>` setzen.
2. Actions → „Build & Deploy“ → *Run workflow* mit dem aktuellen `main`-Commit
   (voller SHA). Das ist der erste PROD-Deploy.
3. Von außen prüfen:
   ```bash
   curl -fsS https://<DOMAIN_PROD>/healthz
   curl -sI https://<DOMAIN_PROD>/ | grep -i -E 'strict-transport|location'
   curl -s -o /dev/null -w '%{http_code}\n' https://<DOMAIN_PROD>/idp/admin/   # 404
   ```
   Login im Browser und die Rollen (Lesen / Redaktion / Admin) testen.
4. Erst danach die PROD-Adresse an die Nutzer geben.

---

## Phase 4: Betrieb

**Jede Änderung:** PR → INT prüfen (`projekthfh.tech`) → Merge → INT und PROD
laufen automatisch.

**INT ist geteilt.** INT zeigt immer den zuletzt deployten PR. Hat danach ein
anderer PR deployt, vor dem Merge den eigenen PR erneut deployen: *Re-run* des
Jobs `deploy-int`. Läuft ein INT-Deploy gerade, wartet der nächste. Von mehreren
wartenden bleibt nur der neueste, ältere werden abgebrochen und brauchen ein Re-run.

**Rollback PROD**
- Actions → „Build & Deploy“ → *Run workflow* → SHA eines älteren Commits von
  `main`. Das Image `sha-…` existiert bereits.
- Notfall ohne GitHub: auf dem Server in der `.env` `IMAGE_TAG=sha-<alt>`
  setzen und `docker compose --profile sso up -d` ausführen. Die Konfiguration
  aus dem Repo bleibt dabei auf dem neuen Stand.

**Überwachung**
- `uptime.yml` prüft täglich beide Hosts: `/healthz` und Zertifikat mit weniger
  als 21 Tagen Restlaufzeit. Schlägt das fehl, kommt eine GitHub-Mail an die
  Repo-Beobachter.

**Regelmäßig**

| Wann | Was |
|---|---|
| automatisch | Sicherheitsupdates (`unattended-upgrades`), certbot-Timer |
| monatlich | `apt full-upgrade` und Neustart im Wartungsfenster, erst INT, dann PROD. Dependabot-PRs mergen (laufen über INT) |
| quartalsweise | Backup von PROD auf INT zurückspielen und testen. Liste prüfen, wer SSH auf PROD und Admin in Keycloak hat |
| jährlich und beim Ausscheiden eines Teammitglieds | `SSH_PRIVATE_KEY_PROD` rotieren (neues Paar, `authorized_keys` und Secret tauschen) |

**Störungen**

| Symptom | Erste Schritte |
|---|---|
| `deploy-int` rot, Merge gesperrt | Job-Log lesen. Meist `.env`-Prüfung, `nginx -t` oder Health-Check. Fix per neuem Commit im PR |
| `deploy-prod` rot nach Merge | PROD läuft mit dem alten Stand weiter, wenn `nginx -t` scheitert. Sonst `docker compose ps` und `logs` auf PROD, Rollback (oben) |
| 502 | `docker compose ps`: Ist die App `healthy`? `docker compose logs app --tail=100` |
| Zertifikatswarnung | `certbot certificates`, `nginx/README.md` Abschnitt 9 |
| Login geht nicht | `docker compose logs keycloak --tail=100`. `KC_HOSTNAME` und Redirect-URIs zur Domain passend? |
| „Secret SSH_HOST_PROD fehlt“ | Secret im Environment `PROD` anlegen, nicht unter den Repository-Secrets |

Logs: `docker compose logs <dienst>`. Pro Dienst höchstens 5 × 10 MB.
