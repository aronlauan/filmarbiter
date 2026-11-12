from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import Movie
from app.schemas import MovieDetail, MovieSummary
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


@router.get("/{imdb_id}", response_model=MovieDetail)
def detail(imdb_id: str, session: SessionDep) -> MovieDetail:
    movie = session.get(Movie, imdb_id)
    if movie is None:
        raise HTTPException(status_code=404, detail="Movie not found")
    return MovieDetail.from_movie(movie)
