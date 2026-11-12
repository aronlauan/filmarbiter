from datetime import datetime

from sqlalchemy import Engine, select, update
from sqlalchemy.orm import Session

from app.models import Movie, MoviePerson, Person
from ingest import imdb
from tests.conftest import FIXTURES


def _ids(session: Session) -> set[str]:
    return set(session.scalars(select(Movie.imdb_id)))


def test_filters_to_rated_feature_films(session: Session) -> None:
    # Excluded: tt3 short, tt4 adult, tt5 under 5000 votes, tt8 no ratings row.
    assert _ids(session) == {
        "tt0000001",
        "tt0000002",
        "tt0000006",
        "tt0000007",
        "tt0000009",
        "tt0000010",
    }


def test_movie_fields(session: Session) -> None:
    heat = session.get(Movie, "tt0000001")
    assert heat is not None
    assert (heat.title, heat.year, heat.runtime_minutes) == ("Heat", 1995, 170)
    assert heat.genre_list == ["Action", "Crime", "Drama"]
    assert (heat.imdb_rating, heat.imdb_votes) == (8.3, 10000)

    # Null runtime/genres survive as None; min_votes boundary is inclusive.
    gf2022 = session.get(Movie, "tt0000007")
    assert gf2022 is not None
    assert gf2022.runtime_minutes is None and gf2022.genre_list == []

    # Bare double quotes in titles must not be treated as CSV quoting.
    quoted = session.get(Movie, "tt0000009")
    assert quoted is not None
    assert quoted.title == 'He Said "Hi"'
    assert quoted.original_title == 'Il a dit "Salut"'


def test_top_cast_is_capped_and_ordered(session: Session) -> None:
    cast = session.scalars(
        select(MoviePerson)
        .where(MoviePerson.imdb_id == "tt0000001", MoviePerson.role == "cast")
        .order_by(MoviePerson.ordering)
    ).all()
    # Actors/actresses only (no 'self' or 'director'), first 5 by billing, re-numbered 0..4.
    assert [c.person.name for c in cast] == [
        "Al Pacino",
        "Robert De Niro",
        "Val Kilmer",
        "Jon Voight",
        "Amy Brenneman",
    ]
    assert [c.ordering for c in cast] == [0, 1, 2, 3, 4]


def test_crew_roles(session: Session) -> None:
    rows = session.execute(
        select(MoviePerson.role, Person.name, MoviePerson.ordering)
        .join(Person)
        .where(MoviePerson.imdb_id == "tt0000006", MoviePerson.role != "cast")
        .order_by(MoviePerson.role, MoviePerson.ordering)
    ).all()
    assert rows == [
        ("director", "Francis Ford Coppola", 0),
        ("writer", "Mario Puzo", 0),
        ("writer", "Francis Ford Coppola", 1),
    ]


def test_people_are_only_those_credited(session: Session) -> None:
    names = set(session.scalars(select(Person.name)))
    assert "Unused Person" not in names
    assert "Some Narrator" not in names  # 'self' credit
    assert "Tom Sizemore" not in names  # 6th-billed actor
    assert len(names) == 15
    # tt9's director (nm0000099) is missing from name.basics, so the credit is dropped.
    assert session.scalar(select(MoviePerson).where(MoviePerson.imdb_id == "tt0000009")) is None
    assert len(session.scalars(select(MoviePerson)).all()) == 19


def test_reingest_preserves_tmdb_fields_and_removes_stale(catalog: Engine) -> None:
    with catalog.begin() as conn:
        conn.execute(
            update(Movie)
            .where(Movie.imdb_id == "tt0000001")
            .values(tmdb_id=949, overview="A heist.", tmdb_fetched_at=datetime(2026, 1, 1))
        )

    # A stricter threshold drops movies under 6000 votes (tt7, tt9).
    counts = imdb.run(FIXTURES / "imdb", catalog, min_votes=6000)
    assert counts["removed_movies"] == 2

    with Session(catalog) as s:
        assert _ids(s) == {"tt0000001", "tt0000002", "tt0000006", "tt0000010"}
        heat = s.get(Movie, "tt0000001")
        assert heat is not None
        assert (heat.tmdb_id, heat.overview) == (949, "A heist.")
        assert heat.imdb_votes == 10000  # IMDb columns still refreshed
