"""Stellt rollen-geschützte Lese- und Schreibzugriffe auf Beratungsstellen bereit.

Der E-Mail-Versand bleibt clientseitig über einen mailto:-Link; der Server
verarbeitet keine Zugangsdaten und versendet selbst keine E-Mails.
"""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.auth import require_permission
from app.database import get_db
from app.models import Center, Service
from app.schemas import CenterCreate, CenterListResponse, CenterOut, CenterWrite

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
    """Maskiert SQL-LIKE-Platzhalter für eine wörtliche Freitextsuche."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@router.get("/centers", response_model=CenterListResponse)
def list_centers(
    db: Session = Depends(get_db),
    _: dict = Depends(require_permission("read_centers")),
    search: str | None = Query(None, description="Freitextsuche in Name/Ort/PLZ"),
    bundesland: str | None = Query(None, description="Filter auf Bundeslandkuerzel, z.B. SN"),
    angebot: Angebot | None = Query(None, description="Filter auf ein Angebot"),
    limit: int = Query(200, ge=1, le=MAX_PAGE_SIZE),
    offset: int = Query(0, ge=0),
):
    """Liefert aktive Stellen mit Filtern und begrenzter Seitengröße."""
    stmt = select(Center).where(Center.aktiv.is_(True))

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

    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
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
def list_bundeslaender(
    db: Session = Depends(get_db),
    _: dict = Depends(require_permission("read_centers")),
):
    """Listet die Bundesländer, in denen aktive Stellen vorhanden sind."""
    rows = db.execute(
        select(func.trim(Center.bundesland))
        .where(Center.aktiv.is_(True))
        .distinct()
        .order_by(func.trim(Center.bundesland))
    ).scalars().all()
    return [r for r in rows if r]


def _resolve_services(db: Session, names: list[str]) -> list[Service]:
    """Löst Leistungsnamen auf und weist unbekannte Namen zurück."""
    unique_names = list(dict.fromkeys(names))
    if not unique_names:
        return []

    services = db.scalars(select(Service).where(Service.name.in_(unique_names))).all()
    by_name = {service.name: service for service in services}
    missing = sorted(set(unique_names) - by_name.keys())
    if missing:
        raise HTTPException(status_code=422, detail=f"Unknown services: {', '.join(missing)}")
    return [by_name[name] for name in unique_names]


@router.post(
    "/centers",
    response_model=CenterOut,
    status_code=status.HTTP_201_CREATED,
)
def create_center(
    payload: CenterCreate,
    db: Session = Depends(get_db),
    _: dict = Depends(require_permission("write_centers")),
):
    """Legt eine neue Stelle mit der vom Aufrufer vorgegebenen eindeutigen ID an."""
    values = payload.model_dump(exclude={"services"})
    center = Center(**values, services=_resolve_services(db, payload.services))
    db.add(center)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="A center with this ID already exists") from exc
    db.refresh(center)
    return center


@router.put("/centers/{center_id}", response_model=CenterOut)
def update_center(
    center_id: int,
    payload: CenterWrite,
    db: Session = Depends(get_db),
    _: dict = Depends(require_permission("write_centers")),
):
    """Ersetzt alle bearbeitbaren Angaben und aktiviert die Stelle wieder."""
    center = db.get(Center, center_id)
    if center is None:
        raise HTTPException(status_code=404, detail="Center not found")

    values = payload.model_dump(exclude={"services"})
    for field, value in values.items():
        setattr(center, field, value)
    center.services = _resolve_services(db, payload.services)
    center.aktiv = True
    center.updated_at = func.now()
    db.commit()
    db.refresh(center)
    return center


@router.delete("/centers/{center_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_center(
    center_id: int,
    db: Session = Depends(get_db),
    _: dict = Depends(require_permission("write_centers")),
):
    """Deaktiviert die Stelle, ohne den Datenbankeintrag physisch zu löschen."""
    center = db.get(Center, center_id)
    if center is None:
        raise HTTPException(status_code=404, detail="Center not found")
    center.aktiv = False
    center.updated_at = func.now()
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
