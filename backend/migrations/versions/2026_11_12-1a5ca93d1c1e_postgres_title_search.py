"""postgres title search

Revision ID: 1a5ca93d1c1e
Revises: 875fb8291eb5
Create Date: 2026-11-12 18:29:16.661365

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "1a5ca93d1c1e"
down_revision: str | Sequence[str] | None = "875fb8291eb5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Title search index for Postgres (the SQLite equivalent is movie_fts, created in
    the catalog migration). See app/search.py; rebuilt by ingest/imdb.py and
    scripts/copy_to_postgres.py."""
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(
        "CREATE TABLE movie_search ("
        "imdb_id VARCHAR(12) PRIMARY KEY REFERENCES movies (imdb_id) ON DELETE CASCADE, "
        "document TSVECTOR NOT NULL)"
    )
    op.execute("CREATE INDEX ix_movie_search_document ON movie_search USING gin (document)")


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("DROP TABLE IF EXISTS movie_search")
