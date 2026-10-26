"""SQLAlchemy mapping for the normalized PostgreSQL center/service schema."""

from datetime import datetime

from sqlalchemy import CHAR, Column, DateTime, Float, ForeignKey, Integer, String, Table, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

center_services = Table(
    "center_services",
    Base.metadata,
    Column("center_id", ForeignKey("centers.id", ondelete="CASCADE"), primary_key=True),
    Column("service_id", ForeignKey("services.id", ondelete="CASCADE"), primary_key=True),
)


class Service(Base):
    __tablename__ = "services"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text, unique=True)
    beschreibung: Mapped[str] = mapped_column(Text, default="")


class Center(Base):
    __tablename__ = "centers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    zqp_id: Mapped[str | None] = mapped_column(String(32), unique=True, nullable=True)
    name: Mapped[str] = mapped_column(Text, default="")
    bundesland: Mapped[str] = mapped_column(CHAR(2), default="")
    plz: Mapped[str] = mapped_column(CHAR(5), default="")
    ort: Mapped[str] = mapped_column(Text, default="")
    adresse: Mapped[str] = mapped_column(Text, default="")
    email: Mapped[str] = mapped_column(Text, default="")
    telefon: Mapped[str] = mapped_column(Text, default="")
    website: Mapped[str] = mapped_column(Text, default="")
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    aktiv: Mapped[bool] = mapped_column(default=True)
    quelle_updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    services: Mapped[list[Service]] = relationship(secondary=center_services, lazy="selectin")

    def _offers(self, label: str) -> bool:
        return any(service.name == label for service in self.services)

    @property
    def pflegestuetzpunkt(self) -> bool:
        return self._offers("Pflegestützpunkt")

    @property
    def pflegeberatung(self) -> bool:
        return self._offers("Pflegeberatung")

    @property
    def wohnberatung(self) -> bool:
        return self._offers("Wohnberatung")

    @property
    def demenzberatung(self) -> bool:
        return self._offers("Demenzberatung")

    @property
    def angehoerigenberatung(self) -> bool:
        return self._offers("Angehörigenberatung")

    @property
    def betreuungsberatung(self) -> bool:
        return self._offers("Betreuungsberatung")

    @property
    def leistungen(self) -> str:
        return ", ".join(sorted(service.name for service in self.services))
