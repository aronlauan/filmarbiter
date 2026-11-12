"""Process-wide movie index, loaded once at API startup."""

import logging

from fastapi import HTTPException

from app.config import settings
from app.db import engine
from app.recommender.index import MovieIndex

log = logging.getLogger(__name__)

_index: MovieIndex | None = None


def load_index() -> None:
    global _index
    path = settings.data_dir / "vectors.npz"
    if not path.exists():
        log.warning("%s not found; recommendations disabled (run `make vectors`)", path)
        return
    _index = MovieIndex.load(engine, path)


def get_index() -> MovieIndex:
    """FastAPI dependency."""
    if _index is None:
        raise HTTPException(
            status_code=503, detail="Recommendations aren't available yet (vectors not built)."
        )
    return _index
