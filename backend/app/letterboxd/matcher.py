"""Map Letterboxd films to catalog IMDb IDs.

1. Slug cache (letterboxd_slug_map) from earlier network lookups.
2. Normalised title + year against the catalog (title or original title; year
   exact, then +/-1). Accepted only when exactly one catalog movie matches.
3. Subtitle + exact year, for titles formatted differently on each site:
   "Star Wars: The Last Jedi" vs "Star Wars: Episode VIII - The Last Jedi",
   "Dark Phoenix" vs "X-Men: Dark Phoenix". Also only when unique.
4. Network fallback: the Letterboxd film page's IMDb link. Ambiguous titles
   (certainly in the catalog) get up to `ambiguous_budget` lookups; unmatched
   films get only `missing_budget`, most strongly rated first, because on real
   profiles nearly all of them are outside the catalog (measured: 14 hits in
   147 lookups, ~0.5s each).
5. Anything else is unmatched (almost always: not in our 5,000+ votes catalog).
"""

import re
import unicodedata
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import Engine, select
from sqlalchemy.dialects import postgresql, sqlite

from app.letterboxd.client import LetterboxdError, LoggedFilm
from app.models import LetterboxdSlugMap, Movie

AMBIGUOUS_BUDGET = 50
MISSING_BUDGET = 20

_PUNCT = re.compile(r"[^\w\s]")
_SUBTITLE_SEP = re.compile(r":|\s[-–—]\s")
_SPACE = re.compile(r"\s+")


def normalize_title(title: str) -> str:
    """'Amélie', 'AMELIE!' -> 'amelie'; '&' -> 'and'; collapses whitespace."""
    t = unicodedata.normalize("NFKD", title)
    t = "".join(c for c in t if not unicodedata.combining(c)).lower().replace("&", " and ")
    return _SPACE.sub(" ", _PUNCT.sub(" ", t)).strip()


def subtitle(title: str) -> str | None:
    """Normalised text after the last ':' or spaced dash, if any:
    'Star Wars: Episode VIII - The Last Jedi' -> 'the last jedi'."""
    parts = _SUBTITLE_SEP.split(title)
    if len(parts) < 2:
        return None
    return normalize_title(parts[-1]) or None


@dataclass
class MatchStats:
    cached: int = 0
    by_title: int = 0
    by_subtitle: int = 0
    by_network: int = 0
    unmatched: int = 0
    network_lookups: int = 0


class CatalogTitles:
    """(normalised title, year) -> catalog IMDb IDs."""

    def __init__(self, rows: Sequence[tuple[str, str, str | None, int | None]]) -> None:
        self.ids: set[str] = set()
        self._by_key: dict[tuple[str, int | None], set[str]] = defaultdict(set)
        self._by_subtitle: dict[tuple[str, int | None], set[str]] = defaultdict(set)
        for imdb_id, title, original, year in rows:
            self.ids.add(imdb_id)
            for t in {title, original} - {None}:
                self._by_key[(normalize_title(t), year)].add(imdb_id)
                if sub := subtitle(t):
                    self._by_subtitle[(sub, year)].add(imdb_id)

    @classmethod
    def load(cls, eng: Engine) -> "CatalogTitles":
        with eng.connect() as c:
            rows = c.execute(
                select(Movie.imdb_id, Movie.title, Movie.original_title, Movie.year)
            ).all()
        return cls([tuple(r) for r in rows])

    def candidates(self, name: str, year: int | None) -> set[str]:
        key = normalize_title(name)
        exact = self._by_key.get((key, year), set())
        if exact or year is None:
            return set(exact)
        return self._by_key.get((key, year - 1), set()) | self._by_key.get((key, year + 1), set())

    def subtitle_candidates(self, name: str, year: int | None) -> set[str]:
        """Exact-year matches where either side's subtitle equals the other's title
        or subtitle. Only used when `candidates` found nothing."""
        full, sub = normalize_title(name), subtitle(name)
        found = set(self._by_subtitle.get((full, year), set()))
        if sub:
            found |= self._by_subtitle.get((sub, year), set()) | self._by_key.get(
                (sub, year), set()
            )
        return found


def match_films(
    eng: Engine,
    films: Sequence[LoggedFilm],
    lookup_imdb_id: Callable[[str], str | None],
    catalog: CatalogTitles | None = None,
    ambiguous_budget: int = AMBIGUOUS_BUDGET,
    missing_budget: int = MISSING_BUDGET,
) -> tuple[dict[str, str], MatchStats]:
    """Return ({slug: imdb_id} for films in the catalog, stats)."""
    catalog = catalog or CatalogTitles.load(eng)
    stats = MatchStats()
    matched: dict[str, str] = {}

    slugs = [f.slug for f in films]
    with eng.connect() as c:
        cache = {
            row.slug: row.imdb_id
            for row in c.execute(
                select(LetterboxdSlugMap.slug, LetterboxdSlugMap.imdb_id).where(
                    LetterboxdSlugMap.slug.in_(slugs)
                )
            )
        }

    ambiguous: list[LoggedFilm] = []
    missing: list[LoggedFilm] = []
    for f in films:
        if f.slug in cache:
            if cache[f.slug] in catalog.ids:
                matched[f.slug] = cache[f.slug]  # type: ignore[assignment]
                stats.cached += 1
            else:
                stats.unmatched += 1
            continue
        cands = catalog.candidates(f.name, f.year)
        if len(cands) == 1:
            matched[f.slug] = next(iter(cands))
            stats.by_title += 1
        elif cands:
            ambiguous.append(f)
        elif len(subs := catalog.subtitle_candidates(f.name, f.year)) == 1:
            matched[f.slug] = next(iter(subs))
            stats.by_subtitle += 1
        else:
            missing.append(f)

    # Network fallback, most useful first: ambiguous titles are definitely in the
    # catalog; then films whose ratings say the most about the user's taste.
    rated = [f.rating for f in films if f.rating is not None]
    mean = sum(rated) / len(rated) if rated else 3.0
    missing.sort(key=lambda f: (f.rating is None and not f.liked, -abs((f.rating or mean) - mean)))
    opinions = [f for f in missing if f.rating is not None or f.liked]
    queue = ambiguous[:ambiguous_budget] + opinions[:missing_budget]

    resolved: dict[str, str | None] = {}
    for f in queue:
        try:
            imdb_id = lookup_imdb_id(f.slug)
        except LetterboxdError:
            break  # Letterboxd is struggling; keep what we have
        stats.network_lookups += 1
        resolved[f.slug] = imdb_id
        if imdb_id in catalog.ids:
            matched[f.slug] = imdb_id  # type: ignore[assignment]
            stats.by_network += 1

    stats.unmatched = len(films) - len(matched)
    if resolved:
        _save_cache(eng, resolved)
    return matched, stats


def _save_cache(eng: Engine, resolved: dict[str, str | None]) -> None:
    insert = postgresql.insert if eng.dialect.name == "postgresql" else sqlite.insert
    now = datetime.now(UTC).replace(tzinfo=None)
    rows = [{"slug": s, "imdb_id": i, "resolved_at": now} for s, i in resolved.items()]
    with eng.begin() as c:
        stmt = insert(LetterboxdSlugMap).values(rows)
        c.execute(
            stmt.on_conflict_do_update(
                index_elements=[LetterboxdSlugMap.slug],
                set_={"imdb_id": stmt.excluded.imdb_id, "resolved_at": stmt.excluded.resolved_at},
            )
        )
