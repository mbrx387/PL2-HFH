"""AP5: Empfaenger aus der Datenbank ermitteln und in BCC-Gruppen aufteilen.

Der Browser schickt nur Einrichtungs-IDs oder Filter - niemals E-Mail-Adressen.
Die Adressen kommen ausschliesslich aus der Tabelle centers.
"""

import re
from dataclasses import dataclass
from urllib.parse import quote

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Center
from app.routers.centers import Angebot, apply_center_filters

# In den Echtdaten (app/data/pflegestellen.csv) enthalten rund 15 % der
# E-Mail-Felder mehrere Adressen, meist durch ";" getrennt.
_ADDRESS_SEPARATORS = re.compile(r"[;,\s]+")
_FORBIDDEN_IN_ADDRESS = set('<>()[]\\"')


class MailSelectionError(ValueError):
    """Ungueltige oder nicht vorhandene Auswahl."""


class MailtoTooLongError(ValueError):
    """Selbst eine E-Mail mit nur einem Empfaenger passt nicht in einen mailto:-Link."""


@dataclass(frozen=True)
class Recipient:
    center_id: int
    email: str
    bundesland: str = ""


@dataclass(frozen=True)
class RecipientCollection:
    recipients: list[Recipient]
    reached_centers: int
    centers_without_email: int
    centers_without_valid_email: int
    invalid_addresses: int
    duplicate_emails: int


def normalize_email(raw: str) -> str | None:
    """Pragmatische Pruefung einer EINZELNEN Adresse (keine vollstaendige RFC-Pruefung)."""
    email = raw.strip()
    if not email or len(email) > 254 or email.count("@") != 1:
        return None
    if any(ch.isspace() or ord(ch) < 32 or ch in _FORBIDDEN_IN_ADDRESS for ch in email):
        return None
    if any(ch in email for ch in ",;"):
        return None
    local, domain = email.split("@")
    if not local or len(local) > 64 or local.startswith(".") or local.endswith("."):
        return None
    labels = domain.split(".")
    if len(labels) < 2 or any(not label or label.startswith("-") or label.endswith("-") for label in labels):
        return None
    if ".." in email:
        return None
    return email


def split_email_field(raw: str | None) -> tuple[list[str], int]:
    """Zerlegt ein Datenbankfeld wie "a@x.de; b@x.de" in gueltige Einzeladressen.

    Rueckgabe: (gueltige Adressen in Originalreihenfolge, Anzahl unbrauchbarer Teile).
    """
    valid: list[str] = []
    invalid = 0
    for part in _ADDRESS_SEPARATORS.split(raw or ""):
        if not part:
            continue
        email = normalize_email(part)
        if email is None:
            invalid += 1
        else:
            valid.append(email)
    return valid, invalid


def escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def select_centers_by_ids(db: Session, center_ids: list[int]) -> list[Center]:
    ordered_ids = list(dict.fromkeys(center_ids))
    rows = db.execute(select(Center).where(Center.id.in_(ordered_ids))).scalars().all()
    by_id = {center.id: center for center in rows}
    missing = [center_id for center_id in ordered_ids if center_id not in by_id]
    if missing:
        raise MailSelectionError(
            "Unbekannte Einrichtungs-IDs: " + ", ".join(map(str, missing[:10]))
        )
    return [by_id[center_id] for center_id in ordered_ids]


def select_centers_by_filters(
    db: Session,
    *,
    search: str | None,
    bundesland: str | None,
    angebot: Angebot | None,
) -> list[Center]:
    """Dieselben Filter wie GET /api/centers, aber OHNE 200er-Anzeigelimit."""
    stmt = apply_center_filters(select(Center), search=search, bundesland=bundesland, angebot=angebot)
    return list(db.execute(stmt.order_by(Center.ort, Center.name, Center.id)).scalars().all())


def collect_recipients(centers: list[Center]) -> RecipientCollection:
    recipients: list[Recipient] = []
    seen: set[str] = set()
    reached = without_email = without_valid = invalid_total = duplicates = 0
    for center in centers:
        raw = (center.email or "").strip()
        if not raw:
            without_email += 1
            continue
        addresses, invalid = split_email_field(raw)
        invalid_total += invalid
        if not addresses:
            without_valid += 1
            continue
        reached += 1
        for email in addresses:
            key = email.casefold()
            if key in seen:
                duplicates += 1
                continue
            seen.add(key)
            recipients.append(
                Recipient(center_id=center.id, email=email, bundesland=(center.bundesland or "").strip())
            )
    return RecipientCollection(
        recipients=recipients,
        reached_centers=reached,
        centers_without_email=without_email,
        centers_without_valid_email=without_valid,
        invalid_addresses=invalid_total,
        duplicate_emails=duplicates,
    )


def build_mailto_url(emails: list[str], subject: str, body: str) -> str:
    """Baut einen mailto:-Link, der Empfaenger AUSSCHLIESSLICH ins BCC setzt.

    "@" und "," bleiben in den Adressen lesbar (RFC 6068 erlaubt das), alles
    andere wird prozentkodiert. Zeilenumbrueche im Text werden nach RFC 6068
    als %0D%0A uebertragen.
    """
    parts = [
        "bcc=" + quote(",".join(emails), safe="@,"),
        "subject=" + quote(subject, safe=""),
    ]
    if body:
        parts.append("body=" + quote(re.sub(r"\r\n|\r|\n", "\r\n", body), safe=""))
    return "mailto:?" + "&".join(parts)


def split_recipients(
    recipients: list[Recipient],
    *,
    subject: str,
    body: str,
    max_recipients: int,
    max_mailto_length: int,
) -> list[list[Recipient]]:
    """Teilt in Gruppen mit hoechstens max_recipients Adressen UND begrenzter Linklaenge."""
    if not 1 <= max_recipients <= 20 or max_mailto_length < 256:
        raise ValueError("Die BCC-Konfiguration ist ungueltig.")
    batches: list[list[Recipient]] = []
    current: list[Recipient] = []
    for recipient in recipients:
        if len(build_mailto_url([recipient.email], subject, body)) > max_mailto_length:
            raise MailtoTooLongError(
                "Betreff oder Nachricht sind zu lang fuer einen mailto:-Link. Bitte den Text kuerzen."
            )
        candidate = [*current, recipient]
        too_many = len(candidate) > max_recipients
        too_long = len(build_mailto_url([r.email for r in candidate], subject, body)) > max_mailto_length
        if current and (too_many or too_long):
            batches.append(current)
            current = [recipient]
        else:
            current = candidate
    if current:
        batches.append(current)
    return batches


def bundeslaender_of(batch: list[Recipient]) -> list[str]:
    return sorted({recipient.bundesland for recipient in batch if recipient.bundesland})
