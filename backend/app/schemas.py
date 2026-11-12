from pydantic import BaseModel

from app.models import Movie

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
        )
