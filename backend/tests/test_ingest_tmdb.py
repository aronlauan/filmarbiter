import asyncio
from collections import Counter

import httpx
import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.models import Movie, MovieKeyword
from ingest import imdb, tmdb
from tests.conftest import FIXTURES

HEAT = {
    "id": 949,
    "imdb_id": "tt0000001",
    "overview": "  Obsessive master thief Neil McCauley...  ",
    "poster_path": "/heat.jpg",
    "original_language": "en",
    "belongs_to_collection": {"id": 1048282, "name": "Heat Collection"},
    "keywords": {
        "keywords": [
            {"id": 10051, "name": "Heist"},
            {"id": 9748, "name": "revenge"},
            {"id": 10051, "name": "heist"},  # duplicate id
        ]
    },
}
GODFATHER = {
    "id": 238,
    "overview": "Spanning the years 1945 to 1955...",
    "poster_path": "/gf.jpg",
    "original_language": "en",
    "belongs_to_collection": None,
    "keywords": {"keywords": [{"id": 131, "name": "mafia"}]},
}


class FakeTMDB:
    """Routes request paths to canned responses and records calls."""

    def __init__(self, routes: dict[str, list[httpx.Response] | httpx.Response]) -> None:
        self.routes = routes
        self.calls: Counter[str] = Counter()

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/3")
        self.calls[path] += 1
        assert request.url.params["api_key"] == "k" * 32
        route = self.routes.get(path, httpx.Response(404))
        if isinstance(route, list):  # sequence of responses for retry tests
            return route.pop(0) if len(route) > 1 else route[0]
        return route


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make retry backoff instant."""
    real_sleep = asyncio.sleep
    monkeypatch.setattr(tmdb.asyncio, "sleep", lambda _s: real_sleep(0))


def _enrich(engine: Engine, fake: FakeTMDB, ids: list[str] | None = None) -> tmdb.Stats:
    async def go() -> tmdb.Stats:
        client = tmdb.TMDBClient("k" * 32, rps=0, transport=httpx.MockTransport(fake))
        async with client:
            return await tmdb.enrich(engine, client, ids or tmdb.pending_ids(engine))

    return asyncio.run(go())


def _keywords(session: Session, imdb_id: str) -> list[str]:
    return list(
        session.scalars(
            select(MovieKeyword.name)
            .where(MovieKeyword.imdb_id == imdb_id)
            .order_by(MovieKeyword.name)
        )
    )


def test_direct_hit_fallback_and_not_found(catalog: Engine) -> None:
    fake = FakeTMDB(
        {
            "/movie/tt0000001": httpx.Response(200, json=HEAT),
            # Godfather isn't resolvable via /movie/{imdb_id}: fall back to /find.
            "/find/tt0000006": httpx.Response(200, json={"movie_results": [{"id": 238}]}),
            "/movie/238": httpx.Response(200, json=GODFATHER),
            # Everything else 404s on both routes (not on TMDB).
        }
    )
    stats = _enrich(catalog, fake)
    assert (stats.enriched, stats.not_found, stats.failed) == (2, 4, 0)
    assert fake.calls["/movie/tt0000001"] == 1 and fake.calls["/find/tt0000001"] == 0

    with Session(catalog) as s:
        heat = s.get(Movie, "tt0000001")
        assert heat is not None
        assert (heat.tmdb_id, heat.poster_path, heat.collection_id) == (949, "/heat.jpg", 1048282)
        assert heat.overview == "Obsessive master thief Neil McCauley..."
        assert _keywords(s, "tt0000001") == ["heist", "revenge"]  # lowercased, deduped

        gf = s.get(Movie, "tt0000006")
        assert gf is not None
        assert (gf.tmdb_id, gf.collection_id) == (238, None)
        assert _keywords(s, "tt0000006") == ["mafia"]

        missing = s.get(Movie, "tt0000007")
        assert missing is not None
        assert missing.tmdb_id is None and missing.tmdb_fetched_at is not None

    # Resumable: everything was marked fetched, so nothing is pending.
    assert tmdb.pending_ids(catalog) == []


def test_retries_rate_limit_then_succeeds(catalog: Engine) -> None:
    fake = FakeTMDB(
        {
            "/movie/tt0000001": [
                httpx.Response(429, headers={"Retry-After": "1"}),
                httpx.Response(503),
                httpx.Response(200, json=HEAT),
            ]
        }
    )
    stats = _enrich(catalog, fake, ["tt0000001"])
    assert (stats.enriched, stats.failed) == (1, 0)
    assert fake.calls["/movie/tt0000001"] == 3


def test_persistent_failure_is_left_pending(catalog: Engine) -> None:
    fake = FakeTMDB({"/movie/tt0000001": httpx.Response(500)})
    stats = _enrich(catalog, fake, ["tt0000001", "tt0000006"])
    assert (stats.enriched, stats.not_found, stats.failed) == (0, 1, 1)
    assert fake.calls["/movie/tt0000001"] == tmdb.MAX_ATTEMPTS
    # Failed movie stays unmarked so the next run retries it; the 404 one is done.
    pending = tmdb.pending_ids(catalog)
    assert "tt0000001" in pending and "tt0000006" not in pending


def test_bad_api_key_stops_the_run(catalog: Engine) -> None:
    fake = FakeTMDB({"/movie/tt0000001": httpx.Response(401)})
    with pytest.raises(tmdb.TMDBAuthError):
        _enrich(catalog, fake, ["tt0000001"])


def test_missing_api_key() -> None:
    with pytest.raises(ValueError, match="TMDB_API_KEY"):
        tmdb.TMDBClient("  ")


def test_pending_order_and_limit(catalog: Engine) -> None:
    # Most-voted first, so partial runs cover the most popular films.
    assert tmdb.pending_ids(catalog, limit=3) == ["tt0000006", "tt0000010", "tt0000001"]


def test_refetch_replaces_keywords(catalog: Engine) -> None:
    _enrich(catalog, FakeTMDB({"/movie/tt0000001": httpx.Response(200, json=HEAT)}), ["tt0000001"])
    updated = {**HEAT, "keywords": {"keywords": [{"id": 1, "name": "neo-noir"}]}}
    _enrich(
        catalog, FakeTMDB({"/movie/tt0000001": httpx.Response(200, json=updated)}), ["tt0000001"]
    )
    with Session(catalog) as s:
        assert _keywords(s, "tt0000001") == ["neo-noir"]


def test_imdb_reingest_keeps_keywords_and_cascades_stale(catalog: Engine) -> None:
    gf2022 = {**GODFATHER, "id": 1, "keywords": {"keywords": [{"id": 2, "name": "remake"}]}}
    fake = FakeTMDB(
        {
            "/movie/tt0000001": httpx.Response(200, json=HEAT),
            "/movie/tt0000007": httpx.Response(200, json=gf2022),
        }
    )
    _enrich(catalog, fake, ["tt0000001", "tt0000007"])

    imdb.run(FIXTURES / "imdb", catalog, min_votes=6000)  # drops tt0000007

    with Session(catalog) as s:
        assert _keywords(s, "tt0000001") == ["heist", "revenge"]
        assert s.get(Movie, "tt0000007") is None
        assert _keywords(s, "tt0000007") == []  # ON DELETE CASCADE
