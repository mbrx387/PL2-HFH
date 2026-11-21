"""AP5: Ein- und Ausgabeschemas fuer Mail-Vorbereitung, Uebergabe und Historie."""

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.routers.centers import Angebot

DEFAULT_SUBJECT = "Anfrage Pflege-/Beratungsstelle"
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


class MailFilterSelection(BaseModel):
    """Gleiche Filter wie die Ergebnisliste (GET /api/centers)."""

    model_config = ConfigDict(extra="forbid")

    search: str | None = Field(default=None, max_length=200)
    bundesland: str | None = Field(default=None, max_length=2)
    angebot: Angebot | None = None

    @model_validator(mode="after")
    def require_filter(self):
        if not (self.search or "").strip() and not (self.bundesland or "").strip() and not self.angebot:
            raise ValueError("Mindestens ein Filter muss gesetzt sein.")
        return self


class MailPrepareRequest(BaseModel):
    """Entweder center_ids (Checkbox-Auswahl) ODER filters - niemals E-Mail-Adressen."""

    model_config = ConfigDict(extra="forbid")

    center_ids: list[int] | None = Field(default=None, min_length=1, max_length=5000)
    filters: MailFilterSelection | None = None
    subject: str = Field(default=DEFAULT_SUBJECT, max_length=255)
    body: str = Field(default="", max_length=5000)

    @field_validator("center_ids")
    @classmethod
    def validate_ids(cls, ids: list[int] | None):
        if ids is None:
            return None
        if any(center_id <= 0 for center_id in ids):
            raise ValueError("Es werden gueltige Einrichtungs-IDs benoetigt.")
        return list(dict.fromkeys(ids))

    @field_validator("subject")
    @classmethod
    def validate_subject(cls, subject: str):
        subject = subject.strip()
        if not subject:
            raise ValueError("Der E-Mail-Betreff darf nicht leer sein.")
        if _CONTROL_CHARS.search(subject):
            raise ValueError("Der Betreff darf keine Zeilenumbrueche oder Steuerzeichen enthalten.")
        return subject

    @field_validator("body")
    @classmethod
    def normalize_body(cls, body: str):
        # Einheitlich "\n" speichern; der mailto:-Link erhaelt spaeter "\r\n".
        return re.sub(r"\r\n|\r", "\n", body).rstrip()

    @model_validator(mode="after")
    def exactly_one_selection(self):
        if (self.center_ids is None) == (self.filters is None):
            raise ValueError("Bitte entweder center_ids oder filters angeben.")
        return self


class PreparedMailBatch(BaseModel):
    number: int
    recipient_count: int
    bundeslaender: list[str]
    handoff_token: str


class MailPrepareResponse(BaseModel):
    campaign_id: str
    selected_centers: int
    reached_centers: int
    centers_without_email: int
    centers_without_valid_email: int
    invalid_addresses: int
    duplicate_emails: int
    recipient_count: int
    batch_count: int
    batches: list[PreparedMailBatch]


class MailHandoffRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    handoff_token: str = Field(min_length=20, max_length=30_000)


class MailHistoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    campaign_id: str
    batch_number: int
    batch_count: int
    created_at: datetime
    created_by: str | None
    subject: str
    body: str
    recipients: list[str]
    recipient_count: int
    bundeslaender: list[str]
    status: Literal["handoff_attempted"]


class MailHandoffResponse(BaseModel):
    history: MailHistoryOut
    mailto_url: str


class MailHistoryListResponse(BaseModel):
    total: int
    items: list[MailHistoryOut]
