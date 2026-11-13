"""Title search.

This is the only module with dialect-specific SQL. Both backends do the same thing:
every word of the query must be a prefix of a word in the title or original title,
ignoring case and accents; exact title matches rank first, then the most-voted.

- SQLite: an FTS5 table, movie_fts (local development, tests).
- Postgres: a tsvector table, movie_search, with a GIN index (production). Accents are
  stripped in Python, so it needs no extensions (no unaccent / pg_trgm).

Both tables are created by hand in migrations and rebuilt by rebuild_search_index at
the end of each IMDb ingest.
"""

import re
import unicodedata

from sqlalchemy import Connection, bindparam, select, text
from sqlalchemy.orm import Session

from app.models import Movie

_TOKEN_RE = re.compile(r"\w+", re.UNICODE)
_PG_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)  # tsquery treats "_" as a separator
_ARTICLES = ("the", "a", "an")

_ORDER_AND_LIMIT = """
    ORDER BY (lower(m.title) IN (:v0, :v1, :v2, :v3)) DESC, m.imdb_votes DESC
    LIMIT :limit
"""

_SQLITE_SEARCH = text(
    """
    SELECT m.imdb_id
    FROM movie_fts f
    JOIN movies m ON m.imdb_id = f.imdb_id
    WHERE movie_fts MATCH :match
    """
    + _ORDER_AND_LIMIT
)

_PG_SEARCH = text(
    """
    SELECT m.imdb_id
    FROM movie_search f
    JOIN movies m ON m.imdb_id = f.imdb_id
    WHERE f.document @@ to_tsquery('simple', :match)
    """
    + _ORDER_AND_LIMIT
)


def _exact_variants(q: str) -> list[str]:
    """Lowercased titles that count as an exact match for q, ignoring a leading article:
    'godfather' and 'the godfather' both match 'The Godfather'."""
    base = " ".join(q.lower().split())
    first, _, rest = base.partition(" ")
    if first in _ARTICLES and rest:
        base = rest
    return [base] + [f"{a} {base}" for a in _ARTICLES]


def _fts_query(q: str) -> str | None:
    """Turn user input into an FTS5 prefix query: 'the dark kn' -> '"the"* "dark"* "kn"*'."""
    tokens = _TOKEN_RE.findall(q.lower())
    if not tokens:
        return None
    return " ".join(f'"{t}"*' for t in tokens)


def _fold(s: str) -> str:
    """Lowercase and strip accents: 'Amélie' -> 'amelie' (like FTS5 remove_diacritics)."""
    decomposed = unicodedata.normalize("NFKD", s.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _pg_tokens(s: str) -> list[str]:
    return _PG_TOKEN_RE.findall(_fold(s))


def _pg_query(q: str) -> str | None:
    """Postgres prefix tsquery: 'the dark kn' -> 'the:* & dark:* & kn:*'. Tokens are
    letters and digits only, so they can't inject tsquery operators."""
    tokens = _pg_tokens(q)
    if not tokens:
        return None
    return " & ".join(f"{t}:*" for t in tokens)


def search_titles(session: Session, q: str, limit: int = 10) -> list[Movie]:
    """Autocomplete search over titles. Exact title matches first, then by popularity."""
    postgres = session.get_bind().dialect.name == "postgresql"
    match = _pg_query(q) if postgres else _fts_query(q)
    if match is None:
        return []

    v0, v1, v2, v3 = _exact_variants(q)
    ids = (
        session.execute(
            _PG_SEARCH if postgres else _SQLITE_SEARCH,
            {"match": match, "v0": v0, "v1": v1, "v2": v2, "v3": v3, "limit": limit},
        )
        .scalars()
        .all()
    )
    if not ids:
        return []

    by_id = {m.imdb_id: m for m in session.scalars(select(Movie).where(Movie.imdb_id.in_(ids)))}
    return [by_id[i] for i in ids if i in by_id]


def rebuild_search_index(conn: Connection) -> None:
    """Repopulate the title index from the movies table (called at the end of ingest)."""
    if conn.dialect.name == "postgresql":
        _rebuild_pg(conn)
        return
    conn.execute(text("DELETE FROM movie_fts"))
    conn.execute(
        text(
            """
            INSERT INTO movie_fts (imdb_id, title, original_title)
            SELECT imdb_id, title,
                   CASE WHEN original_title IS NOT title THEN original_title END
            FROM movies
            """
        )
    )


def _rebuild_pg(conn: Connection) -> None:
    rows = conn.execute(select(Movie.imdb_id, Movie.title, Movie.original_title)).all()
    docs = [
        {
            "imdb_id": imdb_id,
            "doc": " ".join(
                _pg_tokens(title) + (_pg_tokens(original) if original and original != title else [])
            ),
        }
        for imdb_id, title, original in rows
    ]
    conn.execute(text("DELETE FROM movie_search"))
    if docs:
        conn.execute(
            text(
                "INSERT INTO movie_search (imdb_id, document) "
                "VALUES (:imdb_id, to_tsvector('simple', :doc))"
            ).bindparams(bindparam("imdb_id"), bindparam("doc")),
            docs,
        )
