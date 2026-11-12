"""Process-wide movie index and map, loaded once at API startup."""

import logging

from fastapi import HTTPException

from app.config import settings
from app.db import engine
from app.recommender.index import MovieIndex
from app.recommender.movie_map import MovieMap

log = logging.getLogger(__name__)

_index: MovieIndex | None = None
_map: MovieMap | None = None


def load_index() -> None:
    global _index
    path = settings.data_dir / "vectors.npz"
    if not path.exists():
        log.warning("%s not found; recommendations disabled (run `make vectors`)", path)
        return
    _index = MovieIndex.load(engine, path)


def load_map() -> None:
    """Call after load_index: the map's similarity links come from the index."""
    global _map
    path = settings.data_dir / "map.npz"
    if not path.exists():
        log.warning("%s not found; movie theater disabled (run `make map`)", path)
        return
    _map = MovieMap.load(engine, path, _index, settings.map_candidates)


def get_index() -> MovieIndex:
    """FastAPI dependency."""
    if _index is None:
        raise HTTPException(
            status_code=503, detail="Recommendations aren't available yet (vectors not built)."
        )
    return _index


def get_map() -> MovieMap:
    """FastAPI dependency."""
    if _map is None:
        raise HTTPException(
            status_code=503, detail="The movie map isn't available yet (map not built)."
        )
    return _map
