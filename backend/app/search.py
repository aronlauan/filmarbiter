"""Title search.

This is the only module that uses SQLite-specific SQL (FTS5). When we move to
Postgres, reimplement these two functions with pg_trgm / tsvector and nothing
else needs to change.
"""

import re

from sqlalchemy import Connection, select, text
from sqlalchemy.orm import Session

from app.models import Movie

_TOKEN_RE = re.compile(r"\w+", re.UNICODE)
_ARTICLES = ("the", "a", "an")


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


def search_titles(session: Session, q: str, limit: int = 10) -> list[Movie]:
    """Autocomplete search over titles. Exact title matches first, then by popularity."""
    match = _fts_query(q)
    if match is None:
        return []

    v0, v1, v2, v3 = _exact_variants(q)
    ids = (
        session.execute(
            text(
                """
                SELECT m.imdb_id
                FROM movie_fts f
                JOIN movies m ON m.imdb_id = f.imdb_id
                WHERE movie_fts MATCH :match
                ORDER BY (lower(m.title) IN (:v0, :v1, :v2, :v3)) DESC, m.imdb_votes DESC
                LIMIT :limit
                """
            ),
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
