"""Enrich catalog movies with TMDB data (overview, keywords, poster, collection).

    uv run python -m ingest.tmdb [--all] [--limit N]

Looks movies up by IMDb ID, most-voted first. Resumable: only movies without
`tmdb_fetched_at` are fetched unless --all is given. Movies TMDB doesn't know
are marked fetched with no tmdb_id; transient failures are left unmarked so the
next run retries them.
"""

import argparse
import asyncio
import logging
import random
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import Engine, delete, select, update
from sqlalchemy.dialects import postgresql, sqlite

from app.config import settings
from app.db import engine as default_engine
from app.models import Movie, MovieKeyword

log = logging.getLogger("ingest.tmdb")

API_BASE = "https://api.themoviedb.org/3"
BATCH = 200
MAX_ATTEMPTS = 4


class TMDBError(Exception):
    """A request that still failed after retries."""


class TMDBAuthError(TMDBError):
    """TMDB rejected the API key; no point continuing."""


class TMDBClient:
    """Async TMDB client with auth, a requests-per-second cap and retry/backoff."""

    def __init__(
        self,
        api_key: str,
        *,
        rps: float = 35.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        key = api_key.strip()
        if not key:
            raise ValueError("TMDB_API_KEY is not set (see .env.example)")
        # v4 "read access tokens" are JWTs; v3 keys are 32 hex chars passed as a param.
        headers, params = (
            ({"Authorization": f"Bearer {key}"}, {})
            if key.startswith("eyJ")
            else ({}, {"api_key": key})
        )
        self._http = httpx.AsyncClient(
            base_url=API_BASE,
            headers=headers,
            params=params,
            timeout=httpx.Timeout(10, read=20),
            transport=transport,
        )
        self._interval = 1.0 / rps if rps > 0 else 0.0
        self._next_slot = 0.0
        self._lock = asyncio.Lock()

    async def __aenter__(self) -> "TMDBClient":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self._http.aclose()

    async def _throttle(self) -> None:
        if not self._interval:
            return
        async with self._lock:
            now = time.monotonic()
            wait = self._next_slot - now
            self._next_slot = max(now, self._next_slot) + self._interval
        if wait > 0:
            await asyncio.sleep(wait)

    async def get(self, path: str, **params: Any) -> dict | None:
        """GET a JSON resource. Returns None on 404; raises TMDBError after retries."""
        for attempt in range(MAX_ATTEMPTS):
            await self._throttle()
            try:
                resp = await self._http.get(path, params=params)
            except httpx.TransportError as e:
                err: str = f"{type(e).__name__}: {e}"
                delay = 2**attempt
            else:
                if resp.status_code == 200:
                    return resp.json()
                if resp.status_code == 404:
                    return None
                if resp.status_code == 401:
                    raise TMDBAuthError("TMDB rejected the API key (401)")
                if resp.status_code != 429 and resp.status_code < 500:
                    raise TMDBError(f"{path}: HTTP {resp.status_code}")
                err = f"HTTP {resp.status_code}"
                delay = float(resp.headers.get("Retry-After") or 2**attempt)
            if attempt < MAX_ATTEMPTS - 1:
                await asyncio.sleep(delay + random.random() * 0.5)  # noqa: S311
        raise TMDBError(f"{path}: {err} after {MAX_ATTEMPTS} attempts")

    async def movie_by_imdb_id(self, imdb_id: str) -> dict | None:
        """Full movie record (with keywords) for an IMDb ID, or None if TMDB has no match."""
        # /movie/{id} also accepts IMDb IDs (one request). It's undocumented, so fall back
        # to the documented /find lookup if it 404s.
        data = await self.get(f"/movie/{imdb_id}", append_to_response="keywords")
        if data is not None:
            return data
        found = await self.get(f"/find/{imdb_id}", external_source="imdb_id")
        results = (found or {}).get("movie_results") or []
        if not results:
            return None
        return await self.get(f"/movie/{results[0]['id']}", append_to_response="keywords")


def parse_movie(data: dict) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """TMDB movie JSON -> (movie column values, keyword rows without imdb_id)."""
    collection = data.get("belongs_to_collection") or {}
    fields = {
        "tmdb_id": data["id"],
        "overview": (data.get("overview") or "").strip() or None,
        "poster_path": data.get("poster_path"),
        "original_language": data.get("original_language"),
        "collection_id": collection.get("id"),
    }
    seen: set[int] = set()
    keywords = []
    for kw in (data.get("keywords") or {}).get("keywords") or []:
        if kw["id"] not in seen:
            seen.add(kw["id"])
            keywords.append({"keyword_id": kw["id"], "name": kw["name"].strip().lower()})
    return fields, keywords


@dataclass
class Stats:
    enriched: int = 0
    not_found: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)


def pending_ids(eng: Engine, refresh_all: bool = False, limit: int | None = None) -> list[str]:
    stmt = select(Movie.imdb_id).order_by(Movie.imdb_votes.desc())
    if not refresh_all:
        stmt = stmt.where(Movie.tmdb_fetched_at.is_(None))
    if limit:
        stmt = stmt.limit(limit)
    with eng.connect() as conn:
        return list(conn.scalars(stmt))


def _write_batch(eng: Engine, results: dict[str, dict | None]) -> None:
    now = datetime.now(UTC).replace(tzinfo=None)
    insert = postgresql.insert if eng.dialect.name == "postgresql" else sqlite.insert
    with eng.begin() as conn:
        ids = list(results)
        conn.execute(delete(MovieKeyword).where(MovieKeyword.imdb_id.in_(ids)))
        keyword_rows: list[dict] = []
        for imdb_id, data in results.items():
            if data is None:  # TMDB doesn't know this movie
                values: dict[str, Any] = {"tmdb_id": None, "tmdb_fetched_at": now}
            else:
                fields, keywords = parse_movie(data)
                values = {**fields, "tmdb_fetched_at": now}
                keyword_rows += [{"imdb_id": imdb_id, **kw} for kw in keywords]
            conn.execute(update(Movie).where(Movie.imdb_id == imdb_id).values(**values))
        for i in range(0, len(keyword_rows), 5000):
            conn.execute(insert(MovieKeyword).values(keyword_rows[i : i + 5000]))


async def enrich(
    eng: Engine, client: TMDBClient, imdb_ids: list[str], concurrency: int = 16
) -> Stats:
    stats = Stats()
    sem = asyncio.Semaphore(concurrency)

    async def one(imdb_id: str) -> tuple[str, dict | None | TMDBError]:
        async with sem:
            try:
                return imdb_id, await client.movie_by_imdb_id(imdb_id)
            except TMDBAuthError:
                raise
            except TMDBError as e:
                return imdb_id, e

    t0 = time.perf_counter()
    for start in range(0, len(imdb_ids), BATCH):
        batch = imdb_ids[start : start + BATCH]
        done: dict[str, dict | None] = {}
        for imdb_id, result in await asyncio.gather(*(one(i) for i in batch)):
            if isinstance(result, TMDBError):
                stats.failed += 1
                stats.errors.append(f"{imdb_id}: {result}")
                continue
            done[imdb_id] = result
            if result is None:
                stats.not_found += 1
            else:
                stats.enriched += 1
        _write_batch(eng, done)
        n = start + len(batch)
        rate = n / (time.perf_counter() - t0)
        log.info(
            "%d/%d (%.0f/s) enriched=%d not_found=%d failed=%d",
            n,
            len(imdb_ids),
            rate,
            stats.enriched,
            stats.not_found,
            stats.failed,
        )
    return stats


async def run(
    eng: Engine,
    api_key: str,
    refresh_all: bool = False,
    limit: int | None = None,
    concurrency: int = 16,
) -> Stats:
    ids = pending_ids(eng, refresh_all, limit)
    log.info("%d movies to fetch", len(ids))
    if not ids:
        return Stats()
    async with TMDBClient(api_key) as client:
        return await enrich(eng, client, ids, concurrency)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--all", action="store_true", help="re-fetch already-enriched movies")
    parser.add_argument("--limit", type=int, help="only fetch the N most-voted pending movies")
    parser.add_argument("--concurrency", type=int, default=16)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    # httpx logs full request URLs at INFO, which would include the v3 api_key param.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    stats = asyncio.run(
        run(default_engine, settings.tmdb_api_key, args.all, args.limit, args.concurrency)
    )
    for err in stats.errors[:20]:
        log.warning("failed: %s", err)
    log.info(
        "done: enriched=%d not_found=%d failed=%d", stats.enriched, stats.not_found, stats.failed
    )


if __name__ == "__main__":
    main()
