"""Build the movie catalog from IMDb's non-commercial datasets.

    uv run python -m ingest.imdb [--refresh] [--min-votes N]

Downloads the TSVs (unless already present), filters to feature films with at
least `min_votes` ratings, and upserts movies, people and credits. TMDB columns
on existing movies are left untouched, so re-running this never loses enrichment.
"""

import argparse
import gzip
import logging
import shutil
import tempfile
import time
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path

import httpx
import polars as pl
from sqlalchemy import Engine, delete, func, select, text
from sqlalchemy.dialects import postgresql, sqlite

from app.config import settings
from app.db import engine as default_engine
from app.models import Movie, MoviePerson, Person
from app.search import rebuild_search_index

log = logging.getLogger("ingest.imdb")

DATASETS = ["title.basics", "title.ratings", "title.crew", "title.principals", "name.basics"]
BASE_URL = "https://datasets.imdbws.com"
TOP_CAST = 5
CHUNK = 2000  # rows per INSERT; keeps us under SQLite's 32,766 bound-parameter limit

# IMDb TSVs: tab-separated, "\N" for null, and no quoting (titles contain bare quotes).
_READ_OPTS = dict(separator="\t", quote_char=None, null_values="\\N", infer_schema=False)


# --------------------------------------------------------------------------- download


def ensure_downloaded(imdb_dir: Path, refresh: bool = False) -> None:
    imdb_dir.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=httpx.Timeout(30, read=120), follow_redirects=True) as client:
        for name in DATASETS:
            dest = imdb_dir / f"{name}.tsv.gz"
            if dest.exists() and not refresh:
                continue
            log.info("downloading %s", name)
            part = dest.with_suffix(".part")
            with client.stream("GET", f"{BASE_URL}/{name}.tsv.gz") as resp:
                resp.raise_for_status()
                with part.open("wb") as fh:
                    for chunk in resp.iter_bytes(1 << 20):
                        fh.write(chunk)
            part.replace(dest)


@contextmanager
def decompressed(imdb_dir: Path) -> Iterator[dict[str, Path]]:
    """Yield {dataset: path to plain .tsv}. Gzipped files are expanded to a temp dir
    so polars can scan them lazily (title.principals is ~4 GB uncompressed)."""
    with tempfile.TemporaryDirectory(dir=imdb_dir) as tmp:
        paths: dict[str, Path] = {}
        for name in DATASETS:
            plain = imdb_dir / f"{name}.tsv"
            if plain.exists():  # test fixtures ship uncompressed
                paths[name] = plain
                continue
            out = Path(tmp) / f"{name}.tsv"
            with gzip.open(imdb_dir / f"{name}.tsv.gz", "rb") as src, out.open("wb") as dst:
                shutil.copyfileobj(src, dst, 1 << 20)
            paths[name] = out
        yield paths


def _scan(path: Path) -> pl.LazyFrame:
    return pl.scan_csv(path, truncate_ragged_lines=True, **_READ_OPTS)


# --------------------------------------------------------------------------- transform


def build_movies(paths: dict[str, Path], min_votes: int) -> pl.DataFrame:
    basics = (
        _scan(paths["title.basics"])
        .filter((pl.col("titleType") == "movie") & (pl.col("isAdult") == "0"))
        .select(
            pl.col("tconst").alias("imdb_id"),
            pl.col("primaryTitle").alias("title"),
            pl.col("originalTitle").alias("original_title"),
            pl.col("startYear").cast(pl.Int32, strict=False).alias("year"),
            pl.col("runtimeMinutes").cast(pl.Int32, strict=False).alias("runtime_minutes"),
            pl.col("genres"),
        )
    )
    ratings = _scan(paths["title.ratings"]).select(
        pl.col("tconst").alias("imdb_id"),
        pl.col("averageRating").cast(pl.Float64, strict=False).alias("imdb_rating"),
        pl.col("numVotes").cast(pl.Int64, strict=False).alias("imdb_votes"),
    )
    return (
        basics.join(ratings, on="imdb_id", how="inner")
        .filter(pl.col("imdb_votes") >= min_votes)
        .filter(pl.col("title").is_not_null())
        .collect()
    )


def build_credits(paths: dict[str, Path], movie_ids: pl.Series) -> pl.DataFrame:
    """Directors + writers (title.crew) and top-billed actors (title.principals)."""
    ids = pl.DataFrame({"imdb_id": movie_ids}).lazy()

    crew = _scan(paths["title.crew"]).rename({"tconst": "imdb_id"}).join(ids, on="imdb_id")
    crew_parts = []
    for col, role in (("directors", "director"), ("writers", "writer")):
        crew_parts.append(
            crew.select("imdb_id", pl.col(col).str.split(",").alias("nconst"))
            .filter(pl.col("nconst").is_not_null())
            .with_columns(pl.int_ranges(pl.col("nconst").list.len()).alias("ordering"))
            .explode("nconst", "ordering")
            .with_columns(pl.lit(role).alias("role"))
        )

    cast = (
        _scan(paths["title.principals"])
        .filter(pl.col("category").is_in(["actor", "actress"]))
        .rename({"tconst": "imdb_id"})
        .join(ids, on="imdb_id")
        .with_columns(pl.col("ordering").cast(pl.Int32, strict=False))
        .sort("imdb_id", "ordering")
        .group_by("imdb_id", maintain_order=True)
        .head(TOP_CAST)
        .with_columns(pl.int_range(pl.len()).over("imdb_id").alias("ordering"))
        .select("imdb_id", "nconst", "ordering", pl.lit("cast").alias("role"))
    )

    cols = ["imdb_id", "nconst", "role", "ordering"]
    return (
        pl.concat(
            [p.select(cols) for p in crew_parts] + [cast.select(cols)], how="vertical_relaxed"
        )
        .with_columns(pl.col("ordering").cast(pl.Int32))
        .unique(subset=["imdb_id", "nconst", "role"], keep="first", maintain_order=True)
        .collect()
    )


def build_people(paths: dict[str, Path], nconsts: pl.Series) -> pl.DataFrame:
    wanted = pl.DataFrame({"nconst": nconsts.unique()}).lazy()
    return (
        _scan(paths["name.basics"])
        .select("nconst", pl.col("primaryName").alias("name"))
        .filter(pl.col("name").is_not_null())
        .join(wanted, on="nconst")
        .collect()
    )


# --------------------------------------------------------------------------- load


def _chunks(rows: list[dict], size: int = CHUNK) -> Iterable[list[dict]]:
    for i in range(0, len(rows), size):
        yield rows[i : i + size]


def _insert(eng: Engine):
    return postgresql.insert if eng.dialect.name == "postgresql" else sqlite.insert


IMDB_MOVIE_COLS = [
    "title",
    "original_title",
    "year",
    "runtime_minutes",
    "genres",
    "imdb_rating",
    "imdb_votes",
]


def load_catalog(
    eng: Engine, movies: pl.DataFrame, credits: pl.DataFrame, people: pl.DataFrame
) -> dict[str, int]:
    # Drop credits pointing at people missing from name.basics (FK safety).
    credits = credits.join(people.select("nconst"), on="nconst", how="semi")
    insert = _insert(eng)

    with eng.begin() as conn:
        # Movies: upsert IMDb columns only, preserving TMDB enrichment.
        movie_rows = movies.to_dicts()
        for chunk in _chunks(movie_rows):
            stmt = insert(Movie).values(chunk)
            stmt = stmt.on_conflict_do_update(
                index_elements=[Movie.imdb_id],
                set_={c: stmt.excluded[c] for c in IMDB_MOVIE_COLS},
            )
            conn.execute(stmt)

        # Credits are fully IMDb-derived: replace wholesale.
        conn.execute(delete(MoviePerson))

        # Movies that fell out of the filter (e.g. reclassified) are removed.
        keep = set(movies["imdb_id"].to_list())
        existing = set(conn.scalars(select(Movie.imdb_id)))
        stale = list(existing - keep)
        for i in range(0, len(stale), CHUNK):
            conn.execute(delete(Movie).where(Movie.imdb_id.in_(stale[i : i + CHUNK])))

        for chunk in _chunks(people.to_dicts()):
            stmt = insert(Person).values(chunk)
            conn.execute(
                stmt.on_conflict_do_update(
                    index_elements=[Person.nconst], set_={"name": stmt.excluded.name}
                )
            )

        for chunk in _chunks(credits.to_dicts()):
            conn.execute(insert(MoviePerson).values(chunk))

        # People no longer credited on any catalog movie.
        conn.execute(
            delete(Person).where(~Person.nconst.in_(select(MoviePerson.nconst).distinct()))
        )

        rebuild_search_index(conn)

        counts = {
            "movies": conn.scalar(select(func.count()).select_from(Movie)),
            "people": conn.scalar(select(func.count()).select_from(Person)),
            "credits": conn.scalar(select(func.count()).select_from(MoviePerson)),
            "removed_movies": len(stale),
        }
    if eng.dialect.name == "sqlite":
        with eng.connect() as conn:
            conn.execute(text("PRAGMA optimize"))
    return counts


def run(imdb_dir: Path, eng: Engine, min_votes: int, refresh: bool = False) -> dict[str, int]:
    if not (imdb_dir / "title.basics.tsv").exists():
        ensure_downloaded(imdb_dir, refresh=refresh)
    t0 = time.perf_counter()
    with decompressed(imdb_dir) as paths:
        movies = build_movies(paths, min_votes)
        log.info("movies: %d (>= %d votes)", movies.height, min_votes)
        credits = build_credits(paths, movies["imdb_id"])
        log.info("credits: %d", credits.height)
        people = build_people(paths, credits["nconst"])
        log.info("people: %d", people.height)
    counts = load_catalog(eng, movies, credits, people)
    log.info("loaded %s in %.1fs", counts, time.perf_counter() - t0)
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh", action="store_true", help="re-download IMDb files")
    parser.add_argument("--min-votes", type=int, default=settings.min_votes)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    run(settings.data_dir / "imdb", default_engine, args.min_votes, refresh=args.refresh)


if __name__ == "__main__":
    main()
