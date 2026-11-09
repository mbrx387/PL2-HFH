"""API-Endpunkte fuer Pflege-/Beratungsstellen.

Bewusst NUR lesende (GET) Endpunkte: Der eigentliche "Mail versenden"-Schritt
passiert clientseitig ueber einen mailto:-Link (siehe static/js/app.js) und
loest damit die Standard-Mailbox des Nutzers/der Nutzerin aus. Der Server
verarbeitet dabei keine Zugangsdaten und verschickt selbst keine E-Mails -
das reduziert die Angriffsflaeche und den Datenschutz-Scope erheblich
(kein SMTP-Relay, keine gespeicherten Anmeldedaten). Die BCC-Aufteilung und
die Historie der Uebergaben an das Mailprogramm (AP5) liegen in
app/routers/mail.py; sie nutzt dieselben Filter ueber apply_center_filters().
"""
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.models import Center, Service
from app.schemas import CenterListResponse, CenterOut

router = APIRouter(prefix="/api", tags=["centers"])

MAX_PAGE_SIZE = 500

OFFER_NAMES = {
    "pflegestuetzpunkt": "Pflegestützpunkt",
    "pflegeberatung": "Pflegeberatung",
    "wohnberatung": "Wohnberatung",
    "demenzberatung": "Demenzberatung",
    "angehoerigenberatung": "Angehörigenberatung",
    "betreuungsberatung": "Betreuungsberatung",
}

Angebot = Literal[
    "pflegestuetzpunkt",
    "pflegeberatung",
    "wohnberatung",
    "demenzberatung",
    "angehoerigenberatung",
    "betreuungsberatung",
]


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def apply_center_filters(
    stmt: Select,
    *,
    search: str | None = None,
    bundesland: str | None = None,
    angebot: Angebot | None = None,
) -> Select:
    """Gemeinsame Filterlogik fuer die Ergebnisliste UND die AP5-Mailauswahl."""
    if bundesland:
        stmt = stmt.where(func.trim(Center.bundesland) == bundesland.upper())

    if search and search.strip():
        like = f"%{_escape_like(search.strip())}%"
        stmt = stmt.where(
            Center.name.ilike(like, escape="\\")
            | Center.ort.ilike(like, escape="\\")
            | func.trim(Center.plz).ilike(like, escape="\\")
        )

    if angebot:
        stmt = stmt.where(Center.services.any(Service.name == OFFER_NAMES[angebot]))

    return stmt


@router.get("/centers", response_model=CenterListResponse)
def list_centers(
    db: Session = Depends(get_db),
    search: str | None = Query(None, description="Freitextsuche in Name/Ort/PLZ"),
    bundesland: str | None = Query(None, description="Filter auf Bundeslandkuerzel, z.B. SN"),
    angebot: Angebot | None = Query(None, description="Filter auf ein Angebot"),
    limit: int = Query(200, ge=1, le=MAX_PAGE_SIZE),
    offset: int = Query(0, ge=0),
):
    stmt = apply_center_filters(select(Center), search=search, bundesland=bundesland, angebot=angebot)

    total =db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    items = (
        db.execute(
            stmt.options(selectinload(Center.services))
            .order_by(Center.ort, Center.name)
            .offset(offset)
            .limit(limit)
        )
        .scalars()
        .all()
    )

    return CenterListResponse(
        total=total,
        items=[
            CenterOut.model_validate(i).model_copy(
                update={"plz": i.plz.strip(), "bundesland": i.bundesland.strip()}
            )
            for i in items
        ],
    )


@router.get("/bundeslaender", response_model=list[str])
def list_bundeslaender(db: Session = Depends(get_db)):
    rows = db.execute(
        select(func.trim(Center.bundesland))
        .distinct()
        .order_by(func.trim(Center.bundesland))
    ).scalars().all()
    return [r for r in rows if r]
