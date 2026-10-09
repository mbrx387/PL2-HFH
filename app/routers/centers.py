"""API-Endpunkte fuer Pflege-/Beratungsstellen.

Bewusst NUR lesende (GET) Endpunkte: Der eigentliche "Mail versenden"-Schritt
passiert clientseitig ueber einen mailto:-Link (siehe static/js/app.js) und
loest damit die Standard-Mailbox des Nutzers/der Nutzerin aus. Der Server
verarbeitet dabei keine Zugangsdaten und verschickt selbst keine E-Mails -
das reduziert die Angriffsflaeche und den Datenschutz-Scope erheblich
(kein SMTP-Relay, keine gespeicherten Anmeldedaten, kein Mail-Log am Server).
"""
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.models import Center, Service
from app.schemas import CenterListResponse, CenterOut

router = APIRouter(prefix="/api", tags=["centers"])

MAX_PAGE_SIZE = 500

Angebot = Literal[
    "pflegestuetzpunkt",
    "pflegeberatung",
    "wohnberatung",
    "demenzberatung",
    "angehoerigenberatung",
    "betreuungsberatung",
]

ANGEBOT_SERVICE_NAME = {
    "pflegestuetzpunkt": "Pflegestützpunkt",
    "pflegeberatung": "Pflegeberatung",
    "wohnberatung": "Wohnberatung",
    "demenzberatung": "Demenzberatung",
    "angehoerigenberatung": "Angehörigenberatung",
    "betreuungsberatung": "Betreuungsberatung",
}


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@router.get("/centers", response_model=CenterListResponse)
def list_centers(
    db: Session = Depends(get_db),
    search: str | None = Query(None, description="Freitextsuche in Name/Ort/PLZ"),
    bundesland: str | None = Query(None, description="Filter auf Bundeslandkuerzel, z.B. SN"),
    angebot: Angebot | None = Query(None, description="Filter auf ein Angebot"),
    limit: int = Query(200, ge=1, le=MAX_PAGE_SIZE),
    offset: int = Query(0, ge=0),
):
    stmt = select(Center).options(selectinload(Center.services))

    if bundesland:
        stmt = stmt.where(Center.bundesland == bundesland.upper())

    if search and search.strip():
        like = f"%{_escape_like(search.strip())}%"
        stmt = stmt.where(
            Center.name.ilike(like, escape="\\")
            | Center.ort.ilike(like, escape="\\")
            | Center.plz.ilike(like, escape="\\")
        )

    if angebot:
        stmt = stmt.where(Center.services.any(Service.name == ANGEBOT_SERVICE_NAME[angebot]))

    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    items = db.execute(stmt.order_by(Center.ort, Center.name).offset(offset).limit(limit)).scalars().all()

    return CenterListResponse(total=total, items=[CenterOut.model_validate(i) for i in items])


@router.get("/bundeslaender", response_model=list[str])
def list_bundeslaender(db: Session = Depends(get_db)):
    rows = db.execute(select(Center.bundesland).distinct().order_by(Center.bundesland)).scalars().all()
    return [r for r in rows if r]
