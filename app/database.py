"""SQLAlchemy connection and request-scoped sessions for PostgreSQL."""

from sqlalchemy import URL, create_engine, make_url
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import get_settings


def _create_engine(database_url: str | URL | None = None):
    settings = get_settings()
    raw_url = database_url or settings.database_url or URL.create(
        "postgresql+psycopg",
        username=settings.app_db_user,
        password=settings.app_db_password,
        host=settings.app_db_host,
        port=settings.app_db_port,
        database=settings.app_db_name,
    )
    url = make_url(raw_url) if isinstance(raw_url, str) else raw_url
    options: dict[str, object] = {"future": True}
    if url.get_backend_name() == "sqlite":
        options["connect_args"] = {"check_same_thread": False}
        if url.database in (None, "", ":memory:"):
            options["poolclass"] = StaticPool
    else:
        options["pool_pre_ping"] = True
    return create_engine(url, **options)


engine = _create_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def configure_database(database_url: str | URL | None = None) -> None:
    """Reconfigure the database engine; primarily useful for isolated tests."""
    global engine, SessionLocal
    engine.dispose()
    engine = _create_engine(database_url)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
