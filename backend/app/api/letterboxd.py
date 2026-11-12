from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, selectinload

from app.db import get_engine, get_session
from app.letterboxd import service
from app.letterboxd.client import (
    LetterboxdClient,
    LetterboxdError,
    LetterboxdSource,
    PrivateProfileError,
    UserNotFoundError,
    valid_username,
)
from app.models import LetterboxdImport, Movie, MoviePerson
from app.recommender.engine import RatedFilm, recommend_for_profile
from app.recommender.index import MovieIndex
from app.recommender.state import get_index
from app.schemas import (
    BecauseFilm,
    ImportRequest,
    ImportStatus,
    LetterboxdProfileOut,
    MatchReasons,
    MovieDetail,
    ProfileRecommendation,
    RecommendationsResponse,
    VerifyResponse,
)

router = APIRouter(prefix="/api/letterboxd", tags=["letterboxd"])

_verify_cache = service.VerifyCache()


def get_letterboxd_source() -> LetterboxdSource:
    return LetterboxdClient()


def get_verify_cache() -> service.VerifyCache:
    return _verify_cache


SourceDep = Annotated[LetterboxdSource, Depends(get_letterboxd_source)]
CacheDep = Annotated[service.VerifyCache, Depends(get_verify_cache)]
EngineDep = Annotated[Engine, Depends(get_engine)]

UNAVAILABLE = HTTPException(
    status_code=503,
    detail={"reason": "letterboxd_unavailable", "message": "Letterboxd isn't responding."},
)


def _utc(dt: datetime | None) -> datetime | None:
    """DB timestamps are naive UTC; mark them so clients don't read them as local time."""
    return dt.replace(tzinfo=UTC) if dt is not None and dt.tzinfo is None else dt


def _status(job: LetterboxdImport) -> ImportStatus:
    return ImportStatus(
        job_id=job.id,
        username=job.username,
        status=job.status,  # type: ignore[arg-type]
        phase=job.phase,  # type: ignore[arg-type]
        films_total=job.films_total,
        films_fetched=job.films_fetched,
        films_matched=job.films_matched,
        films_rated=job.films_rated,
        error=job.error,
        created_at=_utc(job.created_at),  # type: ignore[arg-type]
        finished_at=_utc(job.finished_at),
    )


@router.get("/verify/{username}", response_model=VerifyResponse)
async def verify(username: str, source: SourceDep, cache: CacheDep) -> VerifyResponse:
    if not valid_username(username):
        return VerifyResponse(status="invalid")
    try:
        p = await service.verify(username, source, cache)
    except UserNotFoundError:
        return VerifyResponse(status="not_found")
    except PrivateProfileError:
        return VerifyResponse(status="private")
    except LetterboxdError as e:
        raise UNAVAILABLE from e
    return VerifyResponse(
        status="ok",
        profile=LetterboxdProfileOut(
            username=p.username,
            display_name=p.display_name,
            avatar_url=p.avatar_url,
            films_count=p.films_count,
        ),
    )


@router.post("/import", response_model=ImportStatus)
def start_import(
    req: ImportRequest,
    response: Response,
    background: BackgroundTasks,
    eng: EngineDep,
    source: SourceDep,
    cache: CacheDep,
) -> ImportStatus:
    profile = cache.get(req.username) if valid_username(req.username) else None
    if profile is None:
        raise HTTPException(
            status_code=409,
            detail={"reason": "not_verified", "message": "Verify the username first."},
        )
    job, created = service.start_import(eng, profile, refresh=req.refresh)
    if created:
        background.add_task(service.run_import, eng, job.id, source)
        response.status_code = 202
    return _status(job)


@router.get("/import/{job_id}", response_model=ImportStatus)
def import_status(job_id: str, eng: EngineDep) -> ImportStatus:
    job = service.get_import(eng, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail={"reason": "unknown_job"})
    return _status(job)


@router.get("/{username}/recommendations", response_model=RecommendationsResponse)
def recommendations(
    username: str,
    eng: EngineDep,
    session: Annotated[Session, Depends(get_session)],
    index: Annotated[MovieIndex, Depends(get_index)],
    limit: Annotated[int, Query(ge=1, le=30)] = 10,
) -> RecommendationsResponse:
    job = service.latest_import(eng, username) if valid_username(username) else None
    if job is None:
        raise HTTPException(
            status_code=404,
            detail={"reason": "not_imported", "message": "Import this user's films first."},
        )
    films = service.logged_films(eng, username)
    by_imdb = {f.imdb_id: f for f in films if f.imdb_id}
    matches = recommend_for_profile(
        index,
        [RatedFilm(imdb_id=i, rating=f.rating, liked=f.liked) for i, f in by_imdb.items()],
        k=limit,
    )

    ids = {m.imdb_id for m in matches} | {b for m in matches for b in m.because}
    movies = {
        m.imdb_id: m
        for m in session.scalars(
            select(Movie)
            .where(Movie.imdb_id.in_(ids))
            .options(
                selectinload(Movie.keywords),
                selectinload(Movie.people).selectinload(MoviePerson.person),
            )
        )
    }

    def because(imdb_id: str) -> BecauseFilm:
        f, m = by_imdb[imdb_id], movies.get(imdb_id)
        return BecauseFilm(
            imdb_id=imdb_id,
            title=m.title if m else f.name,
            year=m.year if m else f.year,
            rating=f.rating,
            liked=f.liked,
        )

    return RecommendationsResponse(
        username=job.username,
        imported_at=_utc(job.finished_at),
        films_logged=len(films),
        films_matched=len(by_imdb),
        results=[
            ProfileRecommendation(
                movie=MovieDetail.from_movie(movies[m.imdb_id]),
                score=round(m.score, 4),
                reasons=MatchReasons(**m.reasons.__dict__),
                because=[because(b) for b in m.because],
            )
            for m in matches
            if m.imdb_id in movies
        ],
    )
