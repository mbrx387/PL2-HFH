"""SQLAlchemy-Modell fuer eine Pflege-/Beratungsstelle.

Die Feldnamen orientieren sich an app/data/pflegestellen.csv, damit der
Seed-Import (siehe seed.py) 1:1 durchgereicht werden kann.
"""
from sqlalchemy import Boolean, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Center(Base):
    __tablename__ = "centers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, index=True)
    adresse: Mapped[str] = mapped_column(String, default="")
    plz: Mapped[str] = mapped_column(String, index=True, default="")
    ort: Mapped[str] = mapped_column(String, index=True, default="")
    bundesland: Mapped[str] = mapped_column(String, index=True, default="")
    email: Mapped[str] = mapped_column(String, default="")
    telefon: Mapped[str] = mapped_column(String, default="")
    website: Mapped[str] = mapped_column(String, default="")
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)

    pflegestuetzpunkt: Mapped[bool] = mapped_column(Boolean, default=False)
    pflegeberatung: Mapped[bool] = mapped_column(Boolean, default=False)
    wohnberatung: Mapped[bool] = mapped_column(Boolean, default=False)
    demenzberatung: Mapped[bool] = mapped_column(Boolean, default=False)
    angehoerigenberatung: Mapped[bool] = mapped_column(Boolean, default=False)
    betreuungsberatung: Mapped[bool] = mapped_column(Boolean, default=False)

    leistungen: Mapped[str] = mapped_column(String, default="")
