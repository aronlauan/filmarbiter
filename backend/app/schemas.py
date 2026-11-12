from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.models import Movie
from app.recommender.engine import MAX_PICKS

TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p"


def poster_url(poster_path: str | None, size: str = "w342") -> str | None:
    return f"{TMDB_IMAGE_BASE}/{size}{poster_path}" if poster_path else None


class MovieSummary(BaseModel):
    imdb_id: str
    title: str
    year: int | None
    poster_url: str | None

    @classmethod
    def from_movie(cls, m: Movie) -> "MovieSummary":
        return cls(
            imdb_id=m.imdb_id, title=m.title, year=m.year, poster_url=poster_url(m.poster_path)
        )


class PersonCredit(BaseModel):
    nconst: str
    name: str


class MovieDetail(MovieSummary):
    original_title: str | None
    runtime_minutes: int | None
    genres: list[str]
    imdb_rating: float | None
    imdb_votes: int
    overview: str | None
    keywords: list[str]
    directors: list[PersonCredit]
    writers: list[PersonCredit]
    cast: list[PersonCredit]
    imdb_url: str
    letterboxd_url: str

    @classmethod
    def from_movie(cls, m: Movie) -> "MovieDetail":
        def credits(role: str) -> list[PersonCredit]:
            return [
                PersonCredit(nconst=mp.nconst, name=mp.person.name)
                for mp in m.people
                if mp.role == role
            ]

        return cls(
            imdb_id=m.imdb_id,
            title=m.title,
            year=m.year,
            poster_url=poster_url(m.poster_path),
            original_title=m.original_title if m.original_title != m.title else None,
            runtime_minutes=m.runtime_minutes,
            genres=m.genre_list,
            imdb_rating=m.imdb_rating,
            imdb_votes=m.imdb_votes,
            overview=m.overview,
            keywords=[k.name for k in m.keywords],
            directors=credits("director"),
            writers=credits("writer"),
            cast=credits("cast"),
            imdb_url=f"https://www.imdb.com/title/{m.imdb_id}/",
            # Letterboxd redirects /imdb/{id}/ to the film page.
            letterboxd_url=f"https://letterboxd.com/imdb/{m.imdb_id}/",
        )


class BlendRequest(BaseModel):
    imdb_ids: list[str] = Field(min_length=1, max_length=MAX_PICKS)


class MatchReasons(BaseModel):
    keywords: list[str]
    genres: list[str]
    people: list[str]


class BlendResult(BaseModel):
    movie: MovieDetail
    score: float
    reasons: MatchReasons


class BlendResponse(BaseModel):
    picks: list[MovieSummary]
    results: list[BlendResult]


# --- Movie map ------------------------------------------------------------


class MapNodeOut(MovieSummary):
    x: float
    y: float
    section: int  # index into MapResponse.sections
    genres: list[str]  # the film's own IMDb genres (sections only name areas)


class MapSection(BaseModel):
    name: str
    size: int


class MapResponse(BaseModel):
    # Board grid spacing; every node's x and y is a multiple of it.
    grid: float
    nodes: list[MapNodeOut]
    # Areas of the house, each named after its most distinctive genre.
    sections: list[MapSection]
    # Links between similar movies, as index pairs into nodes.
    edges: list[tuple[int, int]]


class MapSeat(BaseModel):
    """A seat made for a movie outside the house's seating (a pick or a result)."""

    imdb_id: str
    x: float
    y: float
    section: int
    links: list[int]  # indexes into MapResponse.nodes
    genres: list[str]


# --- Letterboxd -------------------------------------------------------------


class LetterboxdProfileOut(BaseModel):
    username: str
    display_name: str
    avatar_url: str | None
    films_count: int


class VerifyResponse(BaseModel):
    # ok: exists and is public; not_found / private / invalid (bad username format)
    status: Literal["ok", "not_found", "private", "invalid"]
    profile: LetterboxdProfileOut | None = None


class ImportRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    refresh: bool = False


class ImportStatus(BaseModel):
    job_id: str
    username: str
    status: Literal["pending", "running", "done", "failed"]
    phase: Literal["fetching", "matching", "saving"] | None
    films_total: int | None
    films_fetched: int
    films_matched: int
    films_rated: int
    error: str | None
    created_at: datetime
    finished_at: datetime | None


class BecauseFilm(BaseModel):
    imdb_id: str
    title: str
    year: int | None
    rating: float | None
    liked: bool


class ProfileRecommendation(BaseModel):
    movie: MovieDetail
    score: float
    reasons: MatchReasons
    because: list[BecauseFilm]


class RecommendationsResponse(BaseModel):
    username: str
    imported_at: datetime | None
    films_logged: int
    films_matched: int
    results: list[ProfileRecommendation]
