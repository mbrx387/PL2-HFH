"""SQLAlchemy-Modelle fuer Pflegestellen und ihren Leistungskatalog."""
from datetime import datetime

from sqlalchemy import (
    CHAR,
    TIMESTAMP,
    Boolean,
    Column,
    Float,
    ForeignKey,
    Identity,
    Integer,
    String,
    Table,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

center_services = Table(
    "center_services",
    Base.metadata,
    Column("center_id", ForeignKey("centers.id", ondelete="CASCADE"), primary_key=True),
    Column("service_id", ForeignKey("services.id", ondelete="CASCADE"), primary_key=True),
)


class Center(Base):
    __tablename__ = "centers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    zqp_id: Mapped[str | None] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(Text, default="")
    adresse: Mapped[str] = mapped_column(Text, default="")
    plz: Mapped[str] = mapped_column(CHAR(5), default="")
    ort: Mapped[str] = mapped_column(Text, default="")
    bundesland: Mapped[str] = mapped_column(CHAR(2), default="")
    email: Mapped[str] = mapped_column(Text, default="")
    telefon: Mapped[str] = mapped_column(Text, default="")
    website: Mapped[str] = mapped_column(Text, default="")
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    aktiv: Mapped[bool] = mapped_column(Boolean, default=True)
    quelle_updated_at: Mapped[datetime | None] = mapped_column(TIMESTAMP)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    services: Mapped[list["Service"]] = relationship(
        secondary=center_services, back_populates="centers"
    )

    def _has_service(self, name: str) -> bool:
        return any(service.name == name for service in self.services)

    @property
    def pflegestuetzpunkt(self) -> bool:
        return self._has_service("Pflegestützpunkt")

    @property
    def pflegeberatung(self) -> bool:
        return self._has_service("Pflegeberatung")

    @property
    def wohnberatung(self) -> bool:
        return self._has_service("Wohnberatung")

    @property
    def demenzberatung(self) -> bool:
        return self._has_service("Demenzberatung")

    @property
    def angehoerigenberatung(self) -> bool:
        return self._has_service("Angehörigenberatung")

    @property
    def betreuungsberatung(self) -> bool:
        return self._has_service("Betreuungsberatung")

    @property
    def leistungen(self) -> str:
        return "; ".join(sorted(service.name for service in self.services))


class Service(Base):
    __tablename__ = "services"

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    name: Mapped[str] = mapped_column(Text, unique=True)
    beschreibung: Mapped[str] = mapped_column(Text, default="")
    centers: Mapped[list[Center]] = relationship(
        secondary=center_services, back_populates="services"
    )
