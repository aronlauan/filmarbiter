from collections.abc import Iterator

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings


def make_engine(url: str) -> Engine:
    if url.startswith("sqlite"):
        eng = create_engine(url, connect_args={"check_same_thread": False})
    else:
        # Neon suspends idle computes after ~5 minutes and drops their connections, so
        # check connections before use and don't keep them past that.
        eng = create_engine(url, pool_pre_ping=True, pool_recycle=240)
    if eng.dialect.name == "sqlite":
        # Enforce foreign keys (and ON DELETE CASCADE) like Postgres does.
        @event.listens_for(eng, "connect")
        def _sqlite_pragmas(dbapi_conn, _record) -> None:
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.close()

    return eng


engine = make_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_session() -> Iterator[Session]:
    """FastAPI dependency yielding a DB session."""
    with SessionLocal() as session:
        yield session


def get_engine() -> Engine:
    """FastAPI dependency for code that needs the engine itself (background jobs)."""
    return engine
