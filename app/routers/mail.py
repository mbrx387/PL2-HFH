"""AP5-API: E-Mail-Vorbereitung, Uebergabe an das Mailprogramm und Historie.

Ablauf (jede BCC-Gruppe wird nur durch einen eigenen Klick geoeffnet):

1. POST /api/mail/prepare   - Empfaenger aus der Datenbank ermitteln, in Gruppen
                              (max. 20 BCC, begrenzte Linklaenge) teilen. Speichert
                              NICHTS, liefert pro Gruppe ein signiertes Token.
2. POST /api/mail/handoff   - Token pruefen, Historieneintrag schreiben, mailto:-Link
                              zurueckgeben. Der Browser oeffnet damit das Mailprogramm.
3. GET  /api/mail-history   - Historie fuer Frontend/Dashboard (AP6).

Alle Pfade liegen unter /api und sind damit durch die bestehende
Keycloak-Login-Pflicht (LoginRequiredMiddleware) geschuetzt.
"""

from datetime import UTC, datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from itsdangerous import BadSignature, URLSafeTimedSerializer
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import app.config as config
from app.database import get_db
from app.mail_models import HANDOFF_STATUS, MailHistory
from app.mail_schemas import (
    MailHandoffRequest,
    MailHandoffResponse,
    MailHistoryListResponse,
    MailHistoryOut,
    MailPrepareRequest,
    MailPrepareResponse,
    PreparedMailBatch,
)
from app.mail_service import (
    MailSelectionError,
    MailtoTooLongError,
    build_mailto_url,
    bundeslaender_of,
    collect_recipients,
    escape_like,
    select_centers_by_filters,
    select_centers_by_ids,
    split_recipients,
)

router = APIRouter(prefix="/api", tags=["mail"])

TOKEN_TTL_SECONDS = 60 * 60
_TOKEN_SALT = "ap5-mail-handoff-v2"


def _serializer() -> URLSafeTimedSerializer:
    # config.get_settings() erst zur Laufzeit aufrufen (Tests laden config neu).
    return URLSafeTimedSerializer(config.get_settings().secret_key, salt=_TOKEN_SALT)


def _current_user(request: Request) -> str | None:
    if not config.get_settings().auth_enabled:
        return None
    user = request.session.get("user") or {}
    label = user.get("email") or user.get("name") or user.get("sub")
    return str(label)[:255] if label else None


def _is_text_list(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


@router.post("/mail/prepare", response_model=MailPrepareResponse)
def prepare_mail(payload: MailPrepareRequest, db: Session = Depends(get_db)):
    """Vorschau: ermittelt Empfaenger und Gruppen, schreibt noch KEINE Historie."""
    try:
        if payload.center_ids is not None:
            centers = select_centers_by_ids(db, payload.center_ids)
        else:
            filters = payload.filters
            centers = select_centers_by_filters(
                db, search=filters.search, bundesland=filters.bundesland, angebot=filters.angebot
            )
    except MailSelectionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if not centers:
        raise HTTPException(status_code=422, detail="Keine passenden Einrichtungen gefunden.")
    collection = collect_recipients(centers)
    if not collection.recipients:
        raise HTTPException(
            status_code=422, detail="Keine gueltigen E-Mail-Adressen bei den ausgewaehlten Einrichtungen."
        )

    settings = config.get_settings()
    try:
        batches = split_recipients(
            collection.recipients,
            subject=payload.subject,
            body=payload.body,
            max_recipients=settings.mail_bcc_batch_size,
            max_mailto_length=settings.mail_max_mailto_length,
        )
    except MailtoTooLongError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    signer = _serializer()
    campaign_id = uuid4().hex
    prepared = []
    for number, batch in enumerate(batches, start=1):
        laender = bundeslaender_of(batch)
        token = signer.dumps(
            {
                "id": uuid4().hex,
                "campaign": campaign_id,
                "number": number,
                "count": len(batches),
                "emails": [recipient.email for recipient in batch],
                "laender": laender,
                "subject": payload.subject,
                "body": payload.body,
            }
        )
        prepared.append(
            PreparedMailBatch(
                number=number, recipient_count=len(batch), bundeslaender=laender, handoff_token=token
            )
        )

    return MailPrepareResponse(
        campaign_id=campaign_id,
        selected_centers=len(centers),
        reached_centers=collection.reached_centers,
        centers_without_email=collection.centers_without_email,
        centers_without_valid_email=collection.centers_without_valid_email,
        invalid_addresses=collection.invalid_addresses,
        duplicate_emails=collection.duplicate_emails,
        recipient_count=len(collection.recipients),
        batch_count=len(prepared),
        batches=prepared,
    )


@router.post("/mail/handoff", response_model=MailHandoffResponse)
def handoff_mail(payload: MailHandoffRequest, request: Request, db: Session = Depends(get_db)):
    """Nimmt nur ein von /prepare signiertes Token an, protokolliert und liefert den Link."""
    try:
        data = _serializer().loads(payload.handoff_token, max_age=TOKEN_TTL_SECONDS)
    except BadSignature as exc:  # umfasst auch SignatureExpired
        raise HTTPException(
            status_code=422, detail="Vorbereitung abgelaufen oder ungueltig. Bitte erneut starten."
        ) from exc

    settings = config.get_settings()
    valid = (
        isinstance(data, dict)
        and isinstance(data.get("id"), str)
        and len(data["id"]) == 32
        and isinstance(data.get("campaign"), str)
        and len(data["campaign"]) == 32
        and isinstance(data.get("number"), int)
        and isinstance(data.get("count"), int)
        and 1 <= data["number"] <= data["count"]
        and _is_text_list(data.get("emails"))
        and 1 <= len(data["emails"]) <= settings.mail_bcc_batch_size
        and _is_text_list(data.get("laender"))
        and isinstance(data.get("subject"), str)
        and isinstance(data.get("body"), str)
    )
    if not valid:
        raise HTTPException(status_code=422, detail="Ungueltige Uebergabedaten.")

    mailto_url = build_mailto_url(data["emails"], data["subject"], data["body"])
    if len(mailto_url) > settings.mail_max_mailto_length:
        raise HTTPException(status_code=422, detail="Der mailto:-Link waere zu lang.")

    def find_existing() -> MailHistory | None:
        return db.execute(
            select(MailHistory).where(MailHistory.handoff_id == data["id"])
        ).scalar_one_or_none()

    entry = find_existing()
    if entry is None:
        entry = MailHistory(
            handoff_id=data["id"],
            campaign_id=data["campaign"],
            batch_number=data["number"],
            batch_count=data["count"],
            created_by=_current_user(request),
            subject=data["subject"],
            body=data["body"],
            recipients=data["emails"],
            recipient_count=len(data["emails"]),
            bundeslaender=data["laender"],
            status=HANDOFF_STATUS,
        )
        db.add(entry)
        try:
            db.commit()
            db.refresh(entry)
        except IntegrityError:
            # Zwei gleichzeitige Requests mit demselben Token: nur einer wird gespeichert.
            db.rollback()
            entry = find_existing()
            if entry is None:
                raise

    return MailHandoffResponse(history=MailHistoryOut.model_validate(entry), mailto_url=mailto_url)


@router.get("/mail-history", response_model=MailHistoryListResponse)
def list_mail_history(
    db: Session = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    year: int | None = Query(default=None, ge=2000, le=2100, description="Kalenderjahr (UTC)"),
    month: int | None = Query(default=None, ge=1, le=12, description="Monat 1-12, nur mit year"),
    search: str | None = Query(default=None, max_length=200, description="Suche in Betreff/Nachricht"),
    campaign_id: str | None = Query(default=None, max_length=32),
):
    """Historie, neueste zuerst. Fuer das AP6-Dashboard (Filter Jahr/Monat/Suche)."""
    stmt = select(MailHistory)
    if month is not None and year is None:
        raise HTTPException(status_code=422, detail="month nur zusammen mit year verwenden.")
    if year is not None:
        if month is None:
            start, end = datetime(year, 1, 1, tzinfo=UTC), datetime(year + 1, 1, 1, tzinfo=UTC)
        else:
            start = datetime(year, month, 1, tzinfo=UTC)
            end = datetime(year + (month == 12), month % 12 + 1, 1, tzinfo=UTC)
        stmt = stmt.where(MailHistory.created_at >= start, MailHistory.created_at < end)
    if search and search.strip():
        like = f"%{escape_like(search.strip())}%"
        stmt = stmt.where(
            or_(MailHistory.subject.ilike(like, escape="\\"), MailHistory.body.ilike(like, escape="\\"))
        )
    if campaign_id:
        stmt = stmt.where(MailHistory.campaign_id == campaign_id)

    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = db.execute(
        stmt.order_by(MailHistory.created_at.desc(), MailHistory.id.desc()).offset(offset).limit(limit)
    ).scalars().all()
    return MailHistoryListResponse(total=total, items=[MailHistoryOut.model_validate(row) for row in rows])
