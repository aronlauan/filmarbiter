import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.letterboxd.client import LetterboxdError, LoggedFilm
from app.letterboxd.matcher import CatalogTitles, match_films, normalize_title, subtitle
from app.models import LetterboxdSlugMap

CATALOG = CatalogTitles(
    [
        ("tt1", "Heat", "Heat", 1995),
        ("tt2", "Amélie", "Le Fabuleux Destin d'Amélie Poulain", 2001),
        ("tt3", "Fast & Furious", None, 2009),
        # Two different films, same title and year: ambiguous by title alone.
        ("tt4", "Crash", None, 2004),
        ("tt5", "Crash", None, 2004),
        ("tt6", "Spirited Away", "Sen to Chihiro no kamikakushi", 2001),
        ("tt7", "Star Wars: Episode VIII - The Last Jedi", None, 2017),
        ("tt8", "X-Men: Dark Phoenix", None, 2019),
        ("tt9", "Three Colors: Red", None, 1994),
    ]
)


def film(slug: str, name: str, year: int | None, rating: float | None = None, liked: bool = False):
    return LoggedFilm(slug=slug, name=name, year=year, rating=rating, liked=liked)


class Lookup:
    """Fake Letterboxd film-page lookup that records calls."""

    def __init__(self, answers: dict[str, str | None], fail_after: int | None = None) -> None:
        self.answers = answers
        self.calls: list[str] = []
        self.fail_after = fail_after

    def __call__(self, slug: str) -> str | None:
        if self.fail_after is not None and len(self.calls) >= self.fail_after:
            raise LetterboxdError("blocked")
        self.calls.append(slug)
        return self.answers.get(slug)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Amélie", "amelie"),
        ("AMELIE!", "amelie"),
        ("Fast & Furious", "fast and furious"),
        ("  Spider-Man:   No Way Home ", "spider man no way home"),
    ],
)
def test_normalize_title(raw: str, expected: str) -> None:
    assert normalize_title(raw) == expected


def test_title_year_matching(engine: Engine) -> None:
    films = [
        film("heat-1995", "Heat", 1995),
        film("amelie", "Amelie", 2001),  # accents differ
        film("fast-furious", "Fast and Furious", 2009),  # & vs and
        film("spirited-away", "Spirited Away", 2002),  # off-by-one year
        film("sen-to-chihiro", "Sen to Chihiro no Kamikakushi", 2001),  # original title
    ]
    lookup = Lookup({})
    matched, stats = match_films(engine, films, lookup, CATALOG)
    assert matched == {
        "heat-1995": "tt1",
        "amelie": "tt2",
        "fast-furious": "tt3",
        "spirited-away": "tt6",
        "sen-to-chihiro": "tt6",
    }
    assert stats.by_title == 5 and lookup.calls == []


def test_ambiguous_and_missing_use_network_and_are_cached(engine: Engine) -> None:
    films = [
        film("crash-2004", "Crash", 2004, rating=4.0),  # ambiguous -> network
        film("obscure", "Obscure Short", 2015, rating=5.0),  # not found -> network
        film("unrated", "Another Obscure", 2015),  # unrated, not liked -> skipped
        film("in-letterboxd-only", "Weird", 2016, rating=1.0),  # IMDb id outside catalog
    ]
    lookup = Lookup({"crash-2004": "tt5", "obscure": None, "in-letterboxd-only": "tt999"})
    matched, stats = match_films(engine, films, lookup, CATALOG)
    assert matched == {"crash-2004": "tt5"}
    assert lookup.calls[0] == "crash-2004"  # ambiguous titles go first
    assert "unrated" not in lookup.calls
    assert (stats.by_network, stats.unmatched, stats.network_lookups) == (1, 3, 3)

    with Session(engine) as s:
        cache = dict(s.execute(select(LetterboxdSlugMap.slug, LetterboxdSlugMap.imdb_id)).all())
    assert cache == {"crash-2004": "tt5", "obscure": None, "in-letterboxd-only": "tt999"}

    # Second import: everything resolved from the cache, no network.
    again = Lookup({})
    matched2, stats2 = match_films(engine, films, again, CATALOG)
    assert matched2 == matched
    assert again.calls == []
    assert stats2.cached == 1


def test_network_budget_prefers_strong_opinions(engine: Engine) -> None:
    films = [film(f"mild-{i}", f"Mild {i}", 2000, rating=3.0) for i in range(5)] + [
        film("loved", "Loved Obscurity", 2000, rating=5.0),
        film("hated", "Hated Obscurity", 2000, rating=0.5),
    ]
    lookup = Lookup({})
    match_films(engine, films, lookup, CATALOG, missing_budget=2)
    # Mean is ~2.8, so 5.0 and 0.5 are the furthest from it.
    assert sorted(lookup.calls) == ["hated", "loved"]


def test_letterboxd_errors_stop_lookups_but_keep_matches(engine: Engine) -> None:
    films = [
        film("heat-1995", "Heat", 1995),
        film("crash-a", "Crash", 2004, rating=4.0),
        film("crash-b", "Crash", 2004, rating=2.0),
    ]
    lookup = Lookup({"crash-a": "tt4"}, fail_after=1)
    matched, stats = match_films(engine, films, lookup, CATALOG)
    assert matched == {"heat-1995": "tt1", "crash-a": "tt4"}
    assert stats.network_lookups == 1


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Star Wars: Episode VIII - The Last Jedi", "the last jedi"),
        ("X-Men: Dark Phoenix", "dark phoenix"),  # hyphen inside a word isn't a separator
        ("Spider-Man", None),
        ("Heat", None),
    ],
)
def test_subtitle(raw: str, expected: str | None) -> None:
    assert subtitle(raw) == expected


def test_subtitle_matching(engine: Engine) -> None:
    films = [
        film("the-last-jedi", "Star Wars: The Last Jedi", 2017),  # subtitle <-> subtitle
        film("dark-phoenix", "Dark Phoenix", 2019),  # title <-> catalog subtitle
        film("three-colours-red", "Three Colours: Red", 1994),  # 'Colours' spelling differs
        film("red-2010", "Red", 2010),  # same subtitle, wrong year: no match
    ]
    lookup = Lookup({})
    matched, stats = match_films(engine, films, lookup, CATALOG, missing_budget=0)
    assert matched == {"the-last-jedi": "tt7", "dark-phoenix": "tt8", "three-colours-red": "tt9"}
    assert stats.by_subtitle == 3 and lookup.calls == []
