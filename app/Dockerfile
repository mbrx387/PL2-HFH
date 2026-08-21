# Build-Kontext ist das Repository-Root (siehe docker-compose.yml:
# build.context: . / build.dockerfile: app/Dockerfile), damit das Python-
# Package "app" mit seinem eigenen Namen unter /srv/app landet und die
# Imports im Code ("from app.config import ...") ohne Sonderfälle passen.

# Multi-Stage-Build: hält das finale Image klein und ohne Build-Tools.
FROM python:3.12-slim AS builder

WORKDIR /build
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY app/requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

FROM python:3.12-slim AS runtime

# Non-root User: Container läuft nicht als root (Härtung, siehe README).
RUN groupadd --system app && useradd --system --gid app --create-home app

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH="/srv" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY --from=builder /opt/venv /opt/venv

WORKDIR /srv
COPY --chown=app:app app /srv/app

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz')" || exit 1

# Gunicorn mit Uvicorn-Workern: robuster als der reine uvicorn-Dev-Server
# (mehrere Worker, Prozess-Management, Timeouts) - passend für den
# Produktivbetrieb auf dem Ubuntu-Server.
# Eigene Worker-Klasse (app/gunicorn_worker.py) statt der Standard-
# UvicornWorker: vertraut den X-Forwarded-*-Headern von nginx, damit die App
# hinter dem TLS-Proxy korrekt erkennt, dass sie über https:// angesprochen
# wurde (wichtig u.a. für die OIDC-Redirect-URI, siehe app/auth.py).
CMD ["gunicorn", "app.main:app", \
     "--worker-class", "app.gunicorn_worker.ProxyHeadersUvicornWorker", \
     "--workers", "2", \
     "--bind", "0.0.0.0:8000", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
