import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine, insert, text, update
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.db import get_session, make_engine
from app.main import app
from app.models import Movie, MovieKeyword
from app.recommender.features import BlockWeights
from app.recommender.index import MovieIndex
from ingest import imdb
from ingest.build_vectors import build

BACKEND_DIR = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures"


# Set to a scratch Postgres database to run the suite against Postgres instead of
# SQLite. Every test wipes its public schema, so never point it at real data.
TEST_POSTGRES_URL = os.environ.get("TEST_POSTGRES_URL")


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    """A fresh database (SQLite, or TEST_POSTGRES_URL) with all migrations applied."""
    if TEST_POSTGRES_URL:
        url = Settings.model_validate({"database_url": TEST_POSTGRES_URL}).database_url
        wipe = make_engine(url)
        with wipe.begin() as conn:
            conn.execute(text("DROP SCHEMA public CASCADE"))
            conn.execute(text("CREATE SCHEMA public"))
        wipe.dispose()
    else:
        url = f"sqlite:///{tmp_path / 'test.db'}"
    cfg = Config(BACKEND_DIR / "alembic.ini")
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
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


@pytest.fixture
def index(catalog: Engine, tmp_path: Path) -> MovieIndex:
    """Vectors built from the fixture catalog, saved and loaded like production."""
    with catalog.begin() as conn:
        for imdb_id, overview, coll in [
            ("tt0000001", "a master thief plans one last heist", None),
            ("tt0000002", "two cops investigate a drug lord", None),
            ("tt0000006", "the aging patriarch of a crime dynasty", 230),
            ("tt0000007", "a crime family patriarch hands over power", 230),
        ]:
            conn.execute(
                update(Movie)
                .where(Movie.imdb_id == imdb_id)
                .values(overview=overview, collection_id=coll, original_language="en")
            )
        conn.execute(
            insert(MovieKeyword),
            [
                {"imdb_id": "tt0000001", "keyword_id": 1, "name": "heist"},
                {"imdb_id": "tt0000001", "keyword_id": 2, "name": "sequel"},  # ignored tag
                {"imdb_id": "tt0000002", "keyword_id": 1, "name": "heist"},
                {"imdb_id": "tt0000002", "keyword_id": 2, "name": "sequel"},
            ],
        )
    path = tmp_path / "vectors.npz"
    meta = build(catalog, path, fake_embed, BlockWeights())
    assert meta["movies"] == 6 and path.with_suffix(".json").exists()
    return MovieIndex.load(catalog, path)
