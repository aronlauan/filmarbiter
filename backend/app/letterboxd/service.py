"""Letterboxd flows: verify a username, import their logged films (background job),
and read back the latest import for recommendations."""

import asyncio
import logging
import threading
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import Engine, delete, insert, select, update
from sqlalchemy.orm import Session

from app.letterboxd.client import (
    LetterboxdError,
    LetterboxdSource,
    LoggedFilm,
    Profile,
)
from app.letterboxd.matcher import CatalogTitles, match_films
from app.models import LetterboxdFilm, LetterboxdImport

log = logging.getLogger(__name__)

VERIFY_TIMEOUT_S = 15.0  # letterboxdpy retries internally for minutes; cap it
VERIFY_TTL_S = 3600.0
IMPORT_FRESH_FOR = timedelta(hours=24)
IMPORT_STALE_AFTER = timedelta(minutes=30)  # a "running" job this old died with the server


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class VerifyCache:
    """Successful lookups, so verify -> import doesn't fetch the profile twice.
    Process-local; fine for one API process (move to the DB/Redis when scaling out)."""

    def __init__(self, ttl_s: float = VERIFY_TTL_S) -> None:
        self.ttl_s = ttl_s
        self._items: dict[str, tuple[Profile, float]] = {}
        self._lock = threading.Lock()

    def get(self, username: str) -> Profile | None:
        with self._lock:
            item = self._items.get(username.lower())
            if item and item[1] > time.monotonic():
                return item[0]
            self._items.pop(username.lower(), None)
            return None

    def put(self, profile: Profile) -> None:
        with self._lock:
            self._items[profile.username.lower()] = (profile, time.monotonic() + self.ttl_s)


async def verify(username: str, source: LetterboxdSource, cache: VerifyCache) -> Profile:
    """Profile for an existing user. Raises UserNotFoundError, PrivateProfileError or
    LetterboxdError (including on timeout)."""
    if cached := cache.get(username):
        return cached
    try:
        profile = await asyncio.wait_for(
            asyncio.to_thread(source.profile, username), timeout=VERIFY_TIMEOUT_S
        )
    except TimeoutError as e:
        raise LetterboxdError("timed out talking to Letterboxd") from e
    cache.put(profile)
    return profile


def start_import(
    eng: Engine, profile: Profile, refresh: bool = False
) -> tuple[LetterboxdImport, bool]:
    """Return (job, created). Reuses a running job, or a finished one < 24h old."""
    username = profile.username.lower()
    now = _now()
    with Session(eng, expire_on_commit=False) as s, s.begin():
        # Jobs left "running" by a server restart would otherwise block forever.
        s.execute(
            update(LetterboxdImport)
            .where(
                LetterboxdImport.username == username,
                LetterboxdImport.status.in_(["pending", "running"]),
                LetterboxdImport.created_at < now - IMPORT_STALE_AFTER,
            )
            .values(status="failed", error="interrupted", finished_at=now)
        )
        latest = s.scalars(
            select(LetterboxdImport)
            .where(LetterboxdImport.username == username, LetterboxdImport.status != "failed")
            .order_by(LetterboxdImport.created_at.desc())
            .limit(1)
        ).first()
        if latest is not None:
            in_progress = latest.status in ("pending", "running")
            fresh = latest.finished_at is not None and latest.finished_at > now - IMPORT_FRESH_FOR
            if in_progress or (fresh and not refresh):
                return latest, False

        job = LetterboxdImport(
            id=str(uuid.uuid4()),
            username=username,
            status="pending",
            films_total=profile.films_count,
            films_fetched=0,
            films_matched=0,
            films_rated=0,
            created_at=now,
        )
        s.add(job)
    return job, True


def get_import(eng: Engine, job_id: str) -> LetterboxdImport | None:
    with Session(eng, expire_on_commit=False) as s:
        return s.get(LetterboxdImport, job_id)


def _set(eng: Engine, job_id: str, **values: object) -> None:
    with eng.begin() as c:
        c.execute(update(LetterboxdImport).where(LetterboxdImport.id == job_id).values(**values))


def run_import(
    eng: Engine,
    job_id: str,
    source: LetterboxdSource,
    catalog_loader: Callable[[Engine], CatalogTitles] = CatalogTitles.load,
) -> None:
    """Fetch all logged films, match them to the catalog, and store them.
    Runs in a worker thread (FastAPI BackgroundTasks)."""
    job = get_import(eng, job_id)
    if job is None:
        return
    username = job.username
    _set(eng, job_id, status="running", phase="fetching")
    try:
        films: dict[str, LoggedFilm] = {}
        for page in source.film_pages(username):
            films.update({f.slug: f for f in page})
            _set(eng, job_id, films_fetched=len(films))

        logged = list(films.values())
        _set(eng, job_id, phase="matching")
        matched, stats = match_films(eng, logged, source.film_imdb_id, catalog_loader(eng))
        rows = [
            {
                "username": username,
                "slug": f.slug,
                "name": f.name,
                "year": f.year,
                "rating": f.rating,
                "liked": f.liked,
                "imdb_id": matched.get(f.slug),
            }
            for f in logged
        ]
        _set(eng, job_id, phase="saving")
        with eng.begin() as c:
            c.execute(delete(LetterboxdFilm).where(LetterboxdFilm.username == username))
            for i in range(0, len(rows), 2000):
                c.execute(insert(LetterboxdFilm).values(rows[i : i + 2000]))
            c.execute(
                update(LetterboxdImport)
                .where(LetterboxdImport.id == job_id)
                .values(
                    status="done",
                    phase=None,
                    films_fetched=len(logged),
                    films_matched=len(matched),
                    films_rated=sum(1 for f in logged if f.rating is not None),
                    finished_at=_now(),
                )
            )
        log.info("letterboxd import %s for %s: %d films, %s", job_id, username, len(logged), stats)
    except LetterboxdError as e:
        log.warning("letterboxd import %s failed: %s (%s)", job_id, e.reason, e)
        _set(eng, job_id, status="failed", error=e.reason, finished_at=_now())
    except Exception:
        log.exception("letterboxd import %s crashed", job_id)
        _set(eng, job_id, status="failed", error="internal_error", finished_at=_now())


def latest_import(eng: Engine, username: str) -> LetterboxdImport | None:
    with Session(eng, expire_on_commit=False) as s:
        return s.scalars(
            select(LetterboxdImport)
            .where(LetterboxdImport.username == username.lower(), LetterboxdImport.status == "done")
            .order_by(LetterboxdImport.finished_at.desc())
            .limit(1)
        ).first()


def logged_films(eng: Engine, username: str) -> list[LetterboxdFilm]:
    with Session(eng, expire_on_commit=False) as s:
        return list(
            s.scalars(select(LetterboxdFilm).where(LetterboxdFilm.username == username.lower()))
        )
