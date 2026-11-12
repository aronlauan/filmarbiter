from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db import get_session
from app.models import Movie, MoviePerson
from app.recommender.engine import UnknownMoviesError, blend
from app.recommender.index import MovieIndex
from app.recommender.state import get_index
from app.schemas import (
    BlendRequest,
    BlendResponse,
    BlendResult,
    MatchReasons,
    MovieDetail,
    MovieSummary,
)

router = APIRouter(prefix="/api", tags=["blend"])


@router.post("/blend", response_model=BlendResponse)
def blend_movies(
    req: BlendRequest,
    session: Annotated[Session, Depends(get_session)],
    index: Annotated[MovieIndex, Depends(get_index)],
) -> BlendResponse:
    try:
        matches = blend(index, req.imdb_ids, k=3)
    except UnknownMoviesError as e:
        raise HTTPException(status_code=404, detail={"unknown_imdb_ids": e.imdb_ids}) from e

    picks = list(dict.fromkeys(req.imdb_ids))
    wanted = picks + [m.imdb_id for m in matches]
    movies = {
        m.imdb_id: m
        for m in session.scalars(
            select(Movie)
            .where(Movie.imdb_id.in_(wanted))
            .options(
                selectinload(Movie.keywords),
                selectinload(Movie.people).selectinload(MoviePerson.person),
            )
        )
    }
    return BlendResponse(
        picks=[MovieSummary.from_movie(movies[i]) for i in picks if i in movies],
        results=[
            BlendResult(
                movie=MovieDetail.from_movie(movies[m.imdb_id]),
                score=round(m.score, 4),
                reasons=MatchReasons(**m.reasons.__dict__),
            )
            for m in matches
            if m.imdb_id in movies
        ],
    )
