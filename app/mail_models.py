"""AP5: Historie der Uebergaben an das lokale E-Mail-Programm (mailto:).

Ein Eintrag entsteht, wenn die Anwendung eine BCC-E-Mail an das Mailprogramm
UEBERGIBT. Ob die Mail dort tatsaechlich abgeschickt wurde, kann eine
Webanwendung bei mailto: nicht feststellen. Der Status ist deshalb immer
"handoff_attempted" und niemals "sent" (zusaetzlich per CHECK abgesichert).

Die Tabelle wird auf zwei Wegen angelegt, die dasselbe Schema erzeugen
(geprueft in tests/test_mail.py und tests/test_mail_postgres.py):

- db/init/002_create_mail_history.sql: nur bei FRISCH initialisierten
  PostgreSQL-Volumes (Docker fuehrt db/init/ nur beim ersten Start aus).
- ensure_mail_history_table(): beim App-Start, damit auch eine BESTEHENDE
  Datenbank (z.B. auf dem Server) die Tabelle ohne manuellen Eingriff erhaelt.
"""

from datetime import datetime

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Identity,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    inspect,
    text,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

HANDOFF_STATUS = "handoff_attempted"
MAX_BCC_RECIPIENTS = 20

# Feste, frei gewaehlte Nummer fuer die PostgreSQL-Advisory-Lock-Sperre beim
# Anlegen der Tabelle (siehe ensure_mail_history_table).
_CREATE_TABLE_LOCK_ID = 5_020_001


class MailHistory(Base):
    __tablename__ = "mail_history"
    __table_args__ = (
        UniqueConstraint("handoff_id", name="uq_mail_history_handoff_id"),
        CheckConstraint(
            f"recipient_count BETWEEN 1 AND {MAX_BCC_RECIPIENTS}",
            name="ck_mail_history_recipient_count",
        ),
        CheckConstraint(
            "batch_number BETWEEN 1 AND batch_count", name="ck_mail_history_batch_number"
        ),
        CheckConstraint(f"status = '{HANDOFF_STATUS}'", name="ck_mail_history_status"),
        Index("ix_mail_history_created_at", "created_at"),
        Index("ix_mail_history_campaign_id", "campaign_id"),
    )

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    # Eindeutige ID einer einzelnen BCC-E-Mail: verhindert Doppeleintraege,
    # falls derselbe Klick (z.B. durch Netzwerk-Wiederholung) zweimal ankommt.
    handoff_id: Mapped[str] = mapped_column(String(32), nullable=False)
    # Gemeinsame ID aller BCC-Gruppen, die aus EINER Auswahl entstanden sind.
    campaign_id: Mapped[str] = mapped_column(String(32), nullable=False)
    batch_number: Mapped[int] = mapped_column(Integer, nullable=False)
    batch_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    # Angemeldete Person laut Keycloak-Session (E-Mail, sonst Name/ID);
    # leer, wenn die App lokal ohne Login laeuft (AUTH_ENABLED=false).
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    recipients: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    recipient_count: Mapped[int] = mapped_column(Integer, nullable=False)
    # Bundeslaender der Empfaenger dieser Gruppe (Dimension "Region").
    bundeslaender: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text(f"'{HANDOFF_STATUS}'")
    )


def ensure_mail_history_table(engine: Engine) -> None:
    """Legt NUR die AP5-Tabelle an, falls sie fehlt; andere Tabellen bleiben unberuehrt.

    Gunicorn startet mehrere Worker gleichzeitig. Ohne Sperre koennen zwei
    Worker die Tabelle parallel anlegen, und einer stuerzt mit
    "relation already exists" ab (mit PostgreSQL 16 nachgestellt). Die
    transaktionale Advisory-Lock-Sperre laesst die Worker nacheinander pruefen.
    """
    with engine.begin() as connection:
        if connection.dialect.name == "postgresql":
            connection.execute(
                text("SELECT pg_advisory_xact_lock(:lock_id)"), {"lock_id": _CREATE_TABLE_LOCK_ID}
            )
        MailHistory.__table__.create(bind=connection, checkfirst=True)
        existing = {column["name"] for column in inspect(connection).get_columns("mail_history")}

    missing = sorted(set(MailHistory.__table__.columns.keys()) - existing)
    if missing:
        # Fail-fast wie die Pruefung der Pflicht-Tabellen in main.py: eine alte
        # oder manuell angelegte Tabelle wuerde sonst erst beim Speichern scheitern.
        raise RuntimeError(
            "Tabelle mail_history hat ein veraltetes Schema; fehlende Spalten: "
            + ", ".join(missing)
            + ". Siehe docs/AP5_EMAIL_HISTORY.md, Abschnitt Datenbank."
        )
