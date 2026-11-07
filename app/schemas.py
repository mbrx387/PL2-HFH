"""Pydantic-Schemas fuer die API-Antworten (Validierung + OpenAPI-Doku)."""
from pydantic import BaseModel, ConfigDict, Field, field_validator


class CenterOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    adresse: str
    plz: str
    ort: str
    bundesland: str
    email: str
    telefon: str
    website: str
    latitude: float | None = None
    longitude: float | None = None
    pflegestuetzpunkt: bool
    pflegeberatung: bool
    wohnberatung: bool
    demenzberatung: bool
    angehoerigenberatung: bool
    betreuungsberatung: bool
    leistungen: str


class CenterListResponse(BaseModel):
    total: int
    items: list[CenterOut]


class CenterWrite(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1)
    bundesland: str = Field(min_length=2, max_length=2, pattern=r"^[A-Za-z]{2}$")
    plz: str = Field(pattern=r"^\d{5}$")
    ort: str = Field(min_length=1)
    adresse: str = ""
    email: str = ""
    telefon: str = ""
    website: str = ""
    latitude: float | None = Field(default=None, ge=47, le=56)
    longitude: float | None = Field(default=None, ge=5, le=16)
    services: list[str] = Field(default_factory=list)

    @field_validator("bundesland")
    @classmethod
    def normalize_bundesland(cls, value: str) -> str:
        """Schreibt den Bundeslandcode vor der Speicherung in Großbuchstaben."""
        return value.upper()


class CenterCreate(CenterWrite):
    id: int = Field(gt=0)
