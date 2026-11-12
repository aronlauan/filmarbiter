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
