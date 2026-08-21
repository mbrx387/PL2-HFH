"""Pydantic-Schemas fuer die API-Antworten (Validierung + OpenAPI-Doku)."""
from pydantic import BaseModel, ConfigDict


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
