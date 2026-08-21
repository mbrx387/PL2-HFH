"""API-Endpunkte fuer Pflege-/Beratungsstellen.

Bewusst NUR lesende (GET) Endpunkte: Der eigentliche "Mail versenden"-Schritt
passiert clientseitig ueber einen mailto:-Link (siehe static/js/app.js) und
loest damit die Standard-Mailbox des Nutzers/der Nutzerin aus. Der Server
verarbeitet dabei keine Zugangsdaten und verschickt selbst keine E-Mails -
das reduziert die Angriffsflaeche und den Datenschutz-Scope erheblich
(kein SMTP-Relay, keine gespeicherten Anmeldedaten, kein Mail-Log am Server).
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Center
from app.schemas import CenterListResponse, CenterOut

router = APIRouter(prefix="/api", tags=["centers"])

MAX_PAGE_SIZE = 500


@router.get("/centers", response_model=CenterListResponse)
def list_centers(
    db: Session = Depends(get_db),
    search: str | None = Query(None, description="Freitextsuche in Name/Ort/PLZ"),
    bundesland: str | None = Query(None, description="Filter auf Bundeslandkuerzel, z.B. SN"),
    angebot: str | None = Query(
        None,
        description=(
            "Filter auf ein Angebot: pflegestuetzpunkt, pflegeberatung, "
            "wohnberatung, demenzberatung, angehoerigenberatung, betreuungsberatung"
        ),
    ),
    limit: int = Query(200, ge=1, le=MAX_PAGE_SIZE),
    offset: int = Query(0, ge=0),
):
    stmt = select(Center)

    if bundesland:
        stmt = stmt.where(Center.bundesland == bundesland.upper())

    if search:
        like = f"%{search.strip()}%"
        stmt = stmt.where((Center.name.ilike(like)) | (Center.ort.ilike(like)) | (Center.plz.ilike(like)))

    valid_flags = {
        "pflegestuetzpunkt",
        "pflegeberatung",
        "wohnberatung",
        "demenzberatung",
        "angehoerigenberatung",
        "betreuungsberatung",
    }
    if angebot and angebot in valid_flags:
        stmt = stmt.where(getattr(Center, angebot).is_(True))

    total = len(db.execute(stmt).scalars().all())
    items = db.execute(stmt.order_by(Center.ort, Center.name).offset(offset).limit(limit)).scalars().all()

    return CenterListResponse(total=total, items=[CenterOut.model_validate(i) for i in items])


@router.get("/bundeslaender", response_model=list[str])
def list_bundeslaender(db: Session = Depends(get_db)):
    rows = db.execute(select(Center.bundesland).distinct().order_by(Center.bundesland)).scalars().all()
    return [r for r in rows if r]
