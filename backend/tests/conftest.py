from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.db import get_session, make_engine
from app.main import app
from ingest import imdb

BACKEND_DIR = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    """A fresh SQLite database with all migrations applied."""
    url = f"sqlite:///{tmp_path / 'test.db'}"
    cfg = Config(BACKEND_DIR / "alembic.ini")
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url)
    cfg.attributes["configure_logger"] = False
    command.upgrade(cfg, "head")
    eng = make_engine(url)
    yield eng
    eng.dispose()


@pytest.fixture
def catalog(engine: Engine) -> Engine:
    """Database loaded from the tiny IMDb fixture TSVs."""
    imdb.run(FIXTURES / "imdb", engine, min_votes=5000)
    return engine


@pytest.fixture
def session(catalog: Engine) -> Iterator[Session]:
    with sessionmaker(bind=catalog, expire_on_commit=False)() as s:
        yield s


@pytest.fixture
def client(catalog: Engine) -> Iterator[TestClient]:
    factory = sessionmaker(bind=catalog, expire_on_commit=False)

    def _session() -> Iterator[Session]:
        with factory() as s:
            yield s

    app.dependency_overrides[get_session] = _session
    yield TestClient(app)
    app.dependency_overrides.clear()


def fake_embed(texts: list[str]):
    """Deterministic stand-in for the sentence model: hashed bag of words, unit length.
    Overviews sharing words get similar vectors, which is all the tests need."""
    import zlib

    import numpy as np

    out = np.zeros((len(texts), 64), dtype=np.float32)
    for i, t in enumerate(texts):
        for word in t.lower().split():
            out[i, zlib.crc32(word.encode()) % 64] += 1.0
    norms = np.linalg.norm(out, axis=1, keepdims=True)
    return np.divide(out, norms, out=np.zeros_like(out), where=norms > 0)
