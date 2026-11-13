"""Copy the local SQLite database into Postgres (e.g. Neon), instead of re-running the
IMDb + TMDB ingest against it.

    uv run python -m scripts.copy_to_postgres "postgresql://user:pass@host/db?sslmode=require"
                                             [--replace] [--catalog-only]

Migrates the target to the latest schema, copies every table in dependency order,
then rebuilds the Postgres title search index. Refuses to touch a target that already
has movies unless --replace is given (which empties the copied tables first).
--catalog-only skips the Letterboxd tables (your local test imports). The source is
DATABASE_URL / the default local SQLite file.
"""

import argparse
import logging
import time
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, Table, func, insert, select, text

from app import models
from app.config import Settings, settings
from app.db import Base, make_engine
from app.search import rebuild_search_index

log = logging.getLogger("scripts.copy_to_postgres")

BACKEND_DIR = Path(__file__).resolve().parents[1]
CHUNK = 5000
LETTERBOXD_TABLES = {
    models.LetterboxdSlugMap.__tablename__,
    models.LetterboxdImport.__tablename__,
    models.LetterboxdFilm.__tablename__,
}


def migrate(url: str) -> None:
    cfg = Config(BACKEND_DIR / "alembic.ini")
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))  # ini interpolation
    cfg.attributes["configure_logger"] = False
    command.upgrade(cfg, "head")


def copy_table(table: Table, src: Engine, dst: Engine) -> int:
    n = 0
    with src.connect() as s, dst.begin() as d:
        result = s.execution_options(stream_results=True).execute(select(table))
        while rows := result.fetchmany(CHUNK):
            d.execute(insert(table), [r._asdict() for r in rows])
            n += len(rows)
    return n


def run(target_url: str, replace: bool, catalog_only: bool) -> dict[str, int]:
    target_url = Settings.model_validate({"database_url": target_url}).database_url
    if not target_url.startswith("postgresql"):
        raise SystemExit("target must be a Postgres URL")
    src, dst = make_engine(settings.database_url), make_engine(target_url)
    if src.dialect.name != "sqlite":
        raise SystemExit(f"source must be SQLite (DATABASE_URL is {src.dialect.name})")

    log.info("migrating target to head")
    migrate(target_url)

    tables = [
        t for t in Base.metadata.sorted_tables if not (catalog_only and t.name in LETTERBOXD_TABLES)
    ]
    with dst.begin() as d:
        existing = d.scalar(select(func.count()).select_from(models.Movie))
        if existing and not replace:
            raise SystemExit(f"target already has {existing} movies; pass --replace to overwrite")
        for t in reversed(tables):  # children before parents
            d.execute(t.delete())

    counts = {}
    for t in tables:
        t0 = time.perf_counter()
        counts[t.name] = copy_table(t, src, dst)
        log.info("%s: %d rows (%.1fs)", t.name, counts[t.name], time.perf_counter() - t0)

    with dst.begin() as d:
        rebuild_search_index(d)
    with dst.connect().execution_options(isolation_level="AUTOCOMMIT") as d:
        d.execute(text("ANALYZE"))
    log.info("search index rebuilt; done")
    return counts


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("target_url", help="Postgres connection string (Neon's works as-is)")
    p.add_argument("--replace", action="store_true", help="overwrite a non-empty target")
    p.add_argument("--catalog-only", action="store_true", help="skip the Letterboxd tables")
    a = p.parse_args()
    run(a.target_url, a.replace, a.catalog_only)


if __name__ == "__main__":
    main()
