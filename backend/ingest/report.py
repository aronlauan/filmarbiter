"""Catalog sanity report: row counts, TMDB coverage and a few spot checks.

uv run python -m ingest.report
"""

from sqlalchemy import Engine, func, select

from app.db import engine as default_engine
from app.models import Movie, MovieKeyword, MoviePerson, Person

# Well-known films that should always be present and enriched.
SPOT_CHECKS = {
    "tt0111161": "The Shawshank Redemption",
    "tt0113277": "Heat",
    "tt0245429": "Spirited Away",
    "tt0211915": "Amélie",
    "tt6751668": "Parasite",
}


def report(eng: Engine) -> dict[str, float]:
    with eng.connect() as c:

        def count(stmt) -> int:
            return c.scalar(stmt) or 0

        movies = count(select(func.count()).select_from(Movie))
        fetched = count(select(func.count()).where(Movie.tmdb_fetched_at.is_not(None)))
        matched = count(select(func.count()).where(Movie.tmdb_id.is_not(None)))
        overview = count(select(func.count()).where(Movie.overview.is_not(None)))
        poster = count(select(func.count()).where(Movie.poster_path.is_not(None)))
        with_kw = count(select(func.count(func.distinct(MovieKeyword.imdb_id))))
        stats = {
            "movies": movies,
            "people": count(select(func.count()).select_from(Person)),
            "credits": count(select(func.count()).select_from(MoviePerson)),
            "keywords": count(select(func.count()).select_from(MovieKeyword)),
            "distinct_keywords": count(select(func.count(func.distinct(MovieKeyword.keyword_id)))),
            "tmdb_fetched_pct": 100 * fetched / movies if movies else 0,
            "tmdb_matched_pct": 100 * matched / movies if movies else 0,
            "overview_pct": 100 * overview / movies if movies else 0,
            "poster_pct": 100 * poster / movies if movies else 0,
            "keywords_pct": 100 * with_kw / movies if movies else 0,
        }
        missing = [
            f"{iid} {title}"
            for iid, title in SPOT_CHECKS.items()
            if not c.scalar(select(Movie.tmdb_id).where(Movie.imdb_id == iid))
        ]

    for k, v in stats.items():
        print(f"{k:>20}: {v:,.1f}" if isinstance(v, float) else f"{k:>20}: {v:,}")
    print(f"{'spot checks':>20}: {'ok' if not missing else 'MISSING ' + ', '.join(missing)}")
    return stats


if __name__ == "__main__":
    report(default_engine)
