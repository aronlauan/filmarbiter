from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import Movie
from app.schemas import MovieDetail, MovieSummary, RolledMovie
from app.search import search_titles

router = APIRouter(prefix="/api/movies", tags=["movies"])

SessionDep = Annotated[Session, Depends(get_session)]


@router.get("/search", response_model=list[MovieSummary])
def search(
    session: SessionDep,
    q: Annotated[str, Query(min_length=1, max_length=100)],
    limit: Annotated[int, Query(ge=1, le=25)] = 10,
) -> list[MovieSummary]:
    return [MovieSummary.from_movie(m) for m in search_titles(session, q, limit)]


# A quick pick should be a safe bet: well known, well liked, with a poster to show.
ROLL_MIN_VOTES = 25_000
ROLL_MIN_RATING = 6.5


def _csv(value: str | None, limit: int) -> list[str]:
    return list(dict.fromkeys(v.strip() for v in (value or "").split(",") if v.strip()))[:limit]


def _draw(session: Session, genre: str | None, k: int, skip: list[str]) -> list[Movie]:
    stmt = select(Movie).where(
        Movie.imdb_votes >= ROLL_MIN_VOTES,
        Movie.imdb_rating >= ROLL_MIN_RATING,
        Movie.poster_path.is_not(None),
    )
    if genre:
        # genres is "Crime,Drama"; wrap in commas so "Drama" can't match "Dramedy".
        stmt = stmt.where(("," + Movie.genres + ",").contains(f",{genre},"))
    if skip:
        stmt = stmt.where(Movie.imdb_id.not_in(skip))
    return list(session.scalars(stmt.order_by(func.random()).limit(k)))


@router.get("/roll", response_model=list[RolledMovie])
def roll(
    session: SessionDep,
    genres: Annotated[str, Query(min_length=1, max_length=300)],
    per_genre: Annotated[int, Query(ge=1, le=4)] = 1,
    exclude: Annotated[str | None, Query(max_length=4000)] = None,
) -> list[RolledMovie]:
    """`per_genre` random well-rated movies for each comma-separated IMDb genre, in
    the order given, never the same movie twice. `exclude` lists ids recently shown,
    so repeated rolls don't repeat. Genres with nothing to offer are left out."""
    recent = _csv(exclude, 300)
    chosen: list[str] = []
    out: list[RolledMovie] = []
    for genre in _csv(genres, 12):
        got = _draw(session, genre, per_genre, recent + chosen)
        if len(got) < per_genre:
            # The genre's recent rotation is used up: allow repeats rather than gaps.
            got += _draw(session, genre, per_genre - len(got), chosen + [m.imdb_id for m in got])
        for movie in got:
            chosen.append(movie.imdb_id)
            out.append(RolledMovie(genre=genre, movie=MovieDetail.from_movie(movie)))
    return out


@router.get("/{imdb_id}", response_model=MovieDetail)
def detail(imdb_id: str, session: SessionDep) -> MovieDetail:
    movie = session.get(Movie, imdb_id)
    if movie is None:
        raise HTTPException(status_code=404, detail="Movie not found")
    return MovieDetail.from_movie(movie)
