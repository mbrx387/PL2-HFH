"""Stellt rollen-geschützte Lese- und Schreibzugriffe auf Beratungsstellen bereit.

PR#47 / AP5:
Die E-Mail-Vorbereitung verwendet dieselbe Filterlogik wie die
Einrichtungssuche. Der eigentliche Versand erfolgt clientseitig über mailto:.
"""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import Select, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app import config
from app.auth import has_permission, require_permission
from app.database import get_db
from app.maintenance import MANUAL_ID_START
from app.models import Center, Service
from app.schemas import CenterListResponse, CenterOut, CenterWrite

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

# PR#47 + GEÄNDERT AP6:
# Die Filterlogik aus list_centers() ist in eine wiederverwendbare Funktion
# ausgelagert. GET /api/centers und die E-Mail-Auswahl (app/mail_service.py)
# nutzen so exakt dieselben Suchbedingungen.
# WICHTIG: absichtlich ohne Pagination - die E-Mail-Auswahl muss auch mehr als
# 200 Einrichtungen finden können.
# GEÄNDERT AP6: Es werden ausschließlich aktive Einrichtungen berücksichtigt.
def apply_center_filters(
    stmt: Select,
    *,
    search: str | None = None,
    bundesland: str | None = None,
    angebot: Angebot | None = None,
    aktiv: bool = True,
) -> Select:
    """Gemeinsame Filterlogik für Einrichtungssuche und AP5-Mailauswahl."""
    # GEÄNDERT AP6: Deaktivierte Einrichtungen nicht berücksichtigen (Default aktiv=True).
    stmt = stmt.where(Center.aktiv.is_(aktiv))

    # PR#47: Filter nach Bundesland.
    if bundesland:
        stmt = stmt.where(func.trim(Center.bundesland) == bundesland.upper())

    # PR#47: Freitextsuche nach Name, Ort oder Postleitzahl.
    if search and search.strip():
        like = f"%{_escape_like(search.strip())}%"
        stmt = stmt.where(
            Center.name.ilike(like, escape="\\")
            | Center.ort.ilike(like, escape="\\")
            | func.trim(Center.plz).ilike(like, escape="\\")
        )

    # PR#47: Filter nach Beratungsangebot.
    if angebot:
        stmt = stmt.where(Center.services.any(Service.name == OFFER_NAMES[angebot]))

    return stmt


@router.get("/centers", response_model=CenterListResponse)
def list_centers(
    db: Session = Depends(get_db),
    user: dict = Depends(require_permission("read_centers")),
    search: str | None = Query(None, description="Freitextsuche in Name/Ort/PLZ"),
    bundesland: str | None = Query(None, description="Filter auf Bundeslandkuerzel, z.B. SN"),
    angebot: Angebot | None = Query(None, description="Filter auf ein Angebot"),
    aktiv: bool | None = Query(
        None, description="Deaktivierte statt aktiver Einrichtungen listen (nur Redaktion)"
    ),
    limit: int = Query(200, ge=1, le=MAX_PAGE_SIZE),
    offset: int = Query(0, ge=0),
):
    """Liefert Stellen mit Filtern und begrenzter Seitengröße; deaktivierte nur für die Redaktion."""
    # Issue #85: Deaktivierte Einrichtungen duerfen nicht an reader durchsickern.
    if aktiv is False:
        # Ueber das Modul aufrufen (nicht `from app.config import get_settings`),
        # damit Tests, die app.config neu laden, nicht eine veraltete Settings-Instanz sehen.
        settings = config.get_settings()
        if settings.auth_enabled and not has_permission(user, "write_centers"):
            raise HTTPException(
                status_code=403,
                detail="Deaktivierte Einrichtungen darf nur die Redaktion auflisten",
            )
        aktiv_filter = False
    else:
        aktiv_filter = True
    stmt = apply_center_filters(
        select(Center),
        search=search,
        bundesland=bundesland,
        angebot=angebot,
        aktiv=aktiv_filter,
    )

    total = db.execute(
        select(func.count()).select_from(stmt.subquery())
    ).scalar_one()

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
                update={
                    "plz": i.plz.strip(),
                    "bundesland": i.bundesland.strip(),
                }
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
        raise HTTPException(status_code=422, detail=f"Unbekannte Leistungen: {', '.join(missing)}")
    return [by_name[name] for name in unique_names]


def _apply_manual_lock(center: Center, user: dict) -> None:
    """Issue #85: Sperrt den Eintrag fuer den woechentlichen Import und vermerkt wer/wann."""
    center.manuell_gepflegt = True
    center.manuell_geaendert_von = user.get("preferred_username") or user.get("email")
    center.manuell_geaendert_am = func.now()


@router.post(
    "/centers",
    response_model=CenterOut,
    status_code=status.HTTP_201_CREATED,
)
def create_center(
    payload: CenterWrite,
    db: Session = Depends(get_db),
    user: dict = Depends(require_permission("write_centers")),
):
    """Legt eine neue Stelle an; die ID vergibt der Server (ab 1.000.000) und sperrt sie für den Import."""
    values = payload.model_dump(exclude={"services"})
    # ID serverseitig vergeben (Issue #85): nie aus dem Client-Payload, damit
    # manuelle Einrichtungen immer im eigenen ID-Bereich >= 1.000.000 landen.
    max_id = db.execute(select(func.max(Center.id))).scalar_one() or 0
    next_id = max(max_id + 1, MANUAL_ID_START)
    center = Center(
        id=next_id,
        **values,
        services=_resolve_services(db, payload.services),
    )
    _apply_manual_lock(center, user)
    db.add(center)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="Eine Einrichtung mit dieser ID existiert bereits"
        ) from exc
    db.refresh(center)
    return center


@router.put("/centers/{center_id}", response_model=CenterOut)
def update_center(
    center_id: int,
    payload: CenterWrite,
    db: Session = Depends(get_db),
    user: dict = Depends(require_permission("write_centers")),
):
    """Ersetzt alle bearbeitbaren Angaben, aktiviert die Stelle wieder und sperrt sie für den Import."""
    center = db.get(Center, center_id)
    if center is None:
        raise HTTPException(status_code=404, detail="Einrichtung nicht gefunden")

    values = payload.model_dump(exclude={"services"})
    for field, value in values.items():
        setattr(center, field, value)
    center.services = _resolve_services(db, payload.services)
    center.aktiv = True
    _apply_manual_lock(center, user)
    center.updated_at = func.now()
    db.commit()
    db.refresh(center)
    return center


@router.delete("/centers/{center_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_center(
    center_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(require_permission("write_centers")),
):
    """Deaktiviert die Stelle (kein physisches Löschen) und sperrt sie für den Import."""
    center = db.get(Center, center_id)
    if center is None:
        raise HTTPException(status_code=404, detail="Einrichtung nicht gefunden")
    center.aktiv = False
    _apply_manual_lock(center, user)
    center.updated_at = func.now()
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/centers/{center_id}/manual-lock", status_code=status.HTTP_204_NO_CONTENT)
def remove_manual_lock(
    center_id: int,
    db: Session = Depends(get_db),
    _: dict = Depends(require_permission("write_centers")),
):
    """Hebt den Import-Sperrvermerk auf; der nächste Import übernimmt den Eintrag wieder aus der Quelle."""
    center = db.get(Center, center_id)
    if center is None:
        raise HTTPException(status_code=404, detail="Einrichtung nicht gefunden")
    center.manuell_gepflegt = False
    center.updated_at = func.now()
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
