from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Movie(Base):
    __tablename__ = "movies"

    # --- IMDb fields (owned by ingest/imdb.py; overwritten on every re-ingest) ---
    imdb_id: Mapped[str] = mapped_column(String(12), primary_key=True)  # e.g. "tt0113277"
    title: Mapped[str] = mapped_column(String(512))
    original_title: Mapped[str | None] = mapped_column(String(512))
    year: Mapped[int | None] = mapped_column(Integer, index=True)
    runtime_minutes: Mapped[int | None] = mapped_column(Integer)
    genres: Mapped[str | None] = mapped_column(String(256))  # comma-separated, IMDb order
    imdb_rating: Mapped[float | None] = mapped_column(Float)
    imdb_votes: Mapped[int] = mapped_column(Integer, default=0, index=True)

    # --- TMDB fields (owned by ingest/tmdb.py; untouched by IMDb re-ingest) ---
    tmdb_id: Mapped[int | None] = mapped_column(Integer, index=True)
    overview: Mapped[str | None] = mapped_column(Text)
    poster_path: Mapped[str | None] = mapped_column(String(128))
    original_language: Mapped[str | None] = mapped_column(String(8))
    collection_id: Mapped[int | None] = mapped_column(Integer)
    tmdb_fetched_at: Mapped[datetime | None] = mapped_column(DateTime)

    people: Mapped[list["MoviePerson"]] = relationship(
        back_populates="movie", order_by="MoviePerson.ordering"
    )
    keywords: Mapped[list["MovieKeyword"]] = relationship(
        back_populates="movie", cascade="all, delete-orphan", order_by="MovieKeyword.name"
    )

    @property
    def genre_list(self) -> list[str]:
        return self.genres.split(",") if self.genres else []


class Person(Base):
    __tablename__ = "people"

    nconst: Mapped[str] = mapped_column(String(12), primary_key=True)  # e.g. "nm0000134"
    name: Mapped[str] = mapped_column(String(256))


class MoviePerson(Base):
    """Credits we use for matching: directors, writers and top-billed cast."""

    __tablename__ = "movie_people"

    imdb_id: Mapped[str] = mapped_column(
        ForeignKey("movies.imdb_id", ondelete="CASCADE"), primary_key=True
    )
    nconst: Mapped[str] = mapped_column(ForeignKey("people.nconst"), primary_key=True)
    role: Mapped[str] = mapped_column(String(16), primary_key=True)  # director | writer | cast
    ordering: Mapped[int] = mapped_column(Integer, default=0)

    movie: Mapped[Movie] = relationship(back_populates="people")
    person: Mapped[Person] = relationship(lazy="joined")


class MovieKeyword(Base):
    """TMDB keywords (e.g. "heist", "neo-noir"); owned by ingest/tmdb.py."""

    __tablename__ = "movie_keywords"

    imdb_id: Mapped[str] = mapped_column(
        ForeignKey("movies.imdb_id", ondelete="CASCADE"), primary_key=True
    )
    keyword_id: Mapped[int] = mapped_column(Integer, primary_key=True)  # TMDB keyword id
    name: Mapped[str] = mapped_column(String(128), index=True)

    movie: Mapped[Movie] = relationship(back_populates="keywords")


# --- Letterboxd -------------------------------------------------------------


class LetterboxdSlugMap(Base):
    """Cache of Letterboxd film slug -> IMDb ID resolved via the Letterboxd film page.
    imdb_id is None when Letterboxd has no IMDb link for the film."""

    __tablename__ = "letterboxd_slug_map"

    slug: Mapped[str] = mapped_column(String(256), primary_key=True)
    imdb_id: Mapped[str | None] = mapped_column(String(12))
    resolved_at: Mapped[datetime] = mapped_column(DateTime)


class LetterboxdImport(Base):
    """One import of a user's logged films (an async job)."""

    __tablename__ = "letterboxd_imports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)  # uuid4
    username: Mapped[str] = mapped_column(String(64), index=True)  # lowercased
    status: Mapped[str] = mapped_column(String(16))  # pending | running | done | failed
    phase: Mapped[str | None] = mapped_column(String(16))  # fetching | matching | saving
    films_total: Mapped[int | None] = mapped_column(Integer)  # from the profile stats
    films_fetched: Mapped[int] = mapped_column(Integer, default=0)
    films_matched: Mapped[int] = mapped_column(Integer, default=0)
    films_rated: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(String(64))  # not_found | private | ...
    created_at: Mapped[datetime] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)


class LetterboxdFilm(Base):
    """A film a user has logged, from their latest successful import."""

    __tablename__ = "letterboxd_films"

    username: Mapped[str] = mapped_column(String(64), primary_key=True)
    slug: Mapped[str] = mapped_column(String(256), primary_key=True)
    name: Mapped[str] = mapped_column(String(512))
    year: Mapped[int | None] = mapped_column(Integer)
    rating: Mapped[float | None] = mapped_column(Float)  # 0.5..5 stars; None = unrated
    liked: Mapped[bool] = mapped_column(default=False)
    # Catalog match. No FK: the catalog can change under a stored import.
    imdb_id: Mapped[str | None] = mapped_column(String(12))
