"""In-Memory-Datenbank auf Basis von SQLAlchemy + SQLite.

Warum SQLite ":memory:" statt eines simplen Python-dicts/list?
- Wir bekommen echtes SQL (Filtern, Suche, Sortierung, Indizes) ohne eigenen
  Filter-Code schreiben zu muessen.
- Der Wechsel auf einen "richtigen" Server (Postgres/MySQL) ist spaeter nur
  eine Aenderung der Connection-URL, da wir ueber SQLAlchemy-Modelle
  (siehe models.py) und nicht ueber Rohdaten-Strukturen arbeiten.
- Die Datenbank ist bewusst zustandslos: Beim Start wird sie aus der
  mitgelieferten CSV-Datei (app/data/pflegestellen.csv) befuellt. Das macht
  Container austauschbar/horizontal skalierbar und verhindert, dass wir uns
  auf einer In-Memory-DB "Datenverlust" beim Neustart als echtes Risiko
  einhandeln - die Quelle der Wahrheit ist die versionierte CSV-Datei, nicht
  der Arbeitsspeicher eines einzelnen Containers.

Fuer den Produktivbetrieb mit mehreren Nutzern/mehreren Instanzen ist eine
persistente DB (Postgres) der naechste sinnvolle Schritt - siehe README,
Abschnitt "Naechste Schritte".
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import StaticPool

# StaticPool + check_same_thread=False: Standardmuster, damit alle
# FastAPI-Requests (verschiedene Threads) dieselbe In-Memory-SQLite-Instanz
# statt jeweils eine neue, leere Datenbank sehen.
engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
