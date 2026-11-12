import numpy as np
import pytest

from app.recommender.engine import UnknownMoviesError, _mmr, blend, explain
from app.recommender.features import MovieFeatures, build_matrix
from app.recommender.index import MovieIndex
from tests.conftest import fake_embed

HEIST = dict(
    overview="a crew of professional thieves plans a bank heist while a detective closes in",
    keywords=["heist", "bank robbery", "neo-noir", "thief"],
    genres=["Crime", "Thriller"],
    year=1995,
    language="en",
)
ANIMATION = dict(
    overview="a lonely toy robot goes on a colorful adventure to find his family",
    keywords=["toy", "robot", "friendship", "3d animation"],
    genres=["Animation", "Family"],
    year=2008,
    language="en",
)


def M(imdb_id: str, base: dict, **kw) -> MovieFeatures:
    return MovieFeatures(imdb_id=imdb_id, **{**base, **kw})


def _filler() -> list[MovieFeatures]:
    return [
        MovieFeatures(
            imdb_id=f"f{i}",
            overview=f"a gentle romance about gardening and baking number {i}",
            keywords=[f"tag{i % 4}", "romance"],
            genres=["Romance", "Comedy"],
            people=[(f"p{i % 5}", "cast", 0)],
            year=1970 + i,
            language="fr",
        )
        for i in range(20)
    ]


def make_index(
    movies: list[MovieFeatures],
    quality: dict[str, float] | None = None,
    collection: dict[str, int] | None = None,
    names: dict[str, str] | None = None,
) -> MovieIndex:
    all_movies = movies + _filler()
    matrix, _ = build_matrix(all_movies, fake_embed)
    q = np.array([(quality or {}).get(m.imdb_id, 0.5) for m in all_movies], dtype=np.float32)
    coll = [(collection or {}).get(m.imdb_id) for m in all_movies]
    return MovieIndex.build(all_movies, matrix, q, coll, names or {})


def ids(matches) -> list[str]:
    return [m.imdb_id for m in matches]


def test_returns_closest_and_excludes_picks_and_their_collection() -> None:
    index = make_index(
        [
            M("h1", HEIST),
            M("h2", HEIST, overview="thieves plan a bank heist in the city"),
            M("h3", HEIST, overview="a crew of thieves pulls one last bank heist"),
            M("h1-sequel", HEIST),  # identical content to h1, same collection
            M("a1", ANIMATION),
            M("a2", ANIMATION, overview="toys come alive on an adventure"),
        ],
        collection={"h1": 7, "h1-sequel": 7},
    )
    result = ids(blend(index, ["h1", "h2"], k=3))
    assert result[0] == "h3"
    assert not {"h1", "h2", "h1-sequel"} & set(result)


def test_exceptional_match_from_other_era_and_language_wins() -> None:
    index = make_index(
        [
            M("h1", HEIST),
            M("h2", HEIST),
            # Same content as the picks, but 1960 and Japanese: loses only the era/lang bonus.
            M("jp", HEIST, year=1960, language="ja"),
            # Same era and language, but only a loose content match.
            M(
                "en",
                HEIST,
                overview="a detective investigates a murder in the city",
                keywords=["detective", "thief"],
                genres=["Crime", "Drama"],
            ),
        ]
    )
    assert ids(blend(index, ["h1", "h2"], k=2)) == ["jp", "en"]


def test_same_era_and_language_wins_a_close_call() -> None:
    near = dict(HEIST, keywords=["heist", "bank robbery", "neo-noir"])  # one tag short
    index = make_index(
        [
            M("h1", HEIST),
            M("h2", HEIST),
            M("jp", near, year=1960, language="ja"),
            M("en", near),
        ]
    )
    assert ids(blend(index, ["h1", "h2"], k=2)) == ["en", "jp"]


def test_results_must_fit_every_pick() -> None:
    # Blending a heist film with an animated film should favour the film that has
    # both qualities over one that is a perfect match for only one pick.
    hybrid = M(
        "hybrid",
        HEIST,
        overview="a crew of toy robots plans a bank heist on a colorful adventure",
        keywords=["heist", "bank robbery", "toy", "robot"],
        genres=["Animation", "Crime"],
    )
    index = make_index([M("h1", HEIST), M("a1", ANIMATION), M("h2", HEIST), hybrid])
    assert ids(blend(index, ["h1", "a1"], k=1)) == ["hybrid"]


def test_quality_breaks_ties() -> None:
    index = make_index(
        [M("h1", HEIST), M("good", HEIST), M("bad", HEIST)],
        quality={"good": 1.0, "bad": 0.0},
    )
    assert ids(blend(index, ["h1"], k=2)) == ["good", "bad"]


def test_mmr_prefers_variety_on_near_ties() -> None:
    # dupA/dupB are identical and score 0.90; "other" points elsewhere and scores 0.88.
    # Variety should win the near-tie: take one duplicate, then "other".
    def unit(*v: float) -> np.ndarray:
        a = np.array(v, dtype=np.float32)
        return a / np.linalg.norm(a)

    feats = [MovieFeatures("dupA"), MovieFeatures("dupB"), MovieFeatures("other")]
    matrix = np.stack([unit(0.9, 0.44, 0), unit(0.9, 0.44, 0), unit(0.88, -0.47, 0)])
    index = MovieIndex.build(feats, matrix, np.zeros(3, np.float32), [None] * 3, {})
    scores = np.array([0.90, 0.90, 0.88], dtype=np.float32)
    assert [index.ids[r] for r in _mmr(index, scores, 2)] == ["dupA", "other"]


def test_mmr_does_not_trade_a_much_better_match_for_variety() -> None:
    # Same geometry, but "other" is far less relevant: relevance wins.
    def unit(*v: float) -> np.ndarray:
        a = np.array(v, dtype=np.float32)
        return a / np.linalg.norm(a)

    feats = [MovieFeatures("dupA"), MovieFeatures("dupB"), MovieFeatures("other")]
    matrix = np.stack([unit(0.9, 0.44, 0), unit(0.9, 0.44, 0), unit(0.88, -0.47, 0)])
    index = MovieIndex.build(feats, matrix, np.zeros(3, np.float32), [None] * 3, {})
    scores = np.array([0.90, 0.90, 0.60], dtype=np.float32)
    assert [index.ids[r] for r in _mmr(index, scores, 2)] == ["dupA", "dupB"]


def test_explanations() -> None:
    index = make_index(
        [
            M("h1", HEIST, people=[("nm1", "director", 0), ("nm2", "cast", 0)]),
            M("h2", HEIST, keywords=["heist", "thief", "detective"]),
            M("h3", HEIST, people=[("nm1", "director", 0)], keywords=["heist", "thief", "boat"]),
        ],
        names={"nm1": "Michael Mann"},
    )
    (match,) = [m for m in blend(index, ["h1", "h2"], k=3) if m.imdb_id == "h3"]
    # Shared with both picks first; then rarer before more common.
    assert match.reasons.keywords[:2] == ["heist", "thief"]
    assert match.reasons.genres == ["Crime", "Thriller"]
    assert match.reasons.people == ["Michael Mann (director)"]


def test_duplicates_are_collapsed() -> None:
    index = make_index([M("h1", HEIST), M("h2", HEIST)])
    assert ids(blend(index, ["h1", "h1", "h1"], k=1)) == ["h2"]


def test_pick_count_limits() -> None:
    index = make_index([M(f"h{i}", HEIST) for i in range(7)])
    with pytest.raises(ValueError):
        blend(index, [])
    with pytest.raises(ValueError):
        blend(index, [f"h{i}" for i in range(6)])
    assert len(blend(index, [f"h{i}" for i in range(5)], k=1)) == 1


def test_unknown_ids() -> None:
    index = make_index([M("h1", HEIST)])
    with pytest.raises(UnknownMoviesError) as e:
        blend(index, ["h1", "nope"])
    assert e.value.imdb_ids == ["nope"]


def test_explain_by_rarity_prefers_specific_shared_tags() -> None:
    # "drama-ish" is on every movie; "safecracking" only on a few. Shared with more
    # sources isn't enough to beat a much rarer tag when ranking by count x IDF.
    common = dict(HEIST, keywords=["drama-ish"])
    movies = [M(f"s{i}", common) for i in range(6)]
    # Make "drama-ish" genuinely ubiquitous (like "based on novel or book").
    movies += [M(f"bg{i}", common, overview=f"background film {i}") for i in range(20)]
    movies += [
        M("s6", HEIST, keywords=["drama-ish", "safecracking"]),
        M("s7", HEIST, keywords=["drama-ish", "safecracking"]),
        M("result", HEIST, keywords=["drama-ish", "safecracking"]),
    ]
    index = make_index(movies)
    sources = [index.row[f"s{i}"] for i in range(8)]
    row = index.row["result"]

    assert explain(index, row, sources).keywords[0] == "drama-ish"  # most shared first
    assert explain(index, row, sources, by_rarity=True).keywords[0] == "safecracking"


def test_match_percent_scale() -> None:
    from app.recommender.engine import MATCH_CEIL, MATCH_FLOOR, match_percent

    assert match_percent(MATCH_FLOOR) == 0
    assert match_percent(-1.0) == 0
    assert match_percent(MATCH_CEIL) == 100
    assert match_percent(2.0) == 100
    # Typical scores from the calibration: scattered blend, good blend.
    assert 60 <= match_percent(0.37) <= 70
    assert 80 <= match_percent(0.49) <= 90
    scores = [0.2, 0.3, 0.4, 0.5, 0.6]
    assert [match_percent(s) for s in scores] == sorted(match_percent(s) for s in scores)


def test_explain_never_cites_race_ethnicity_or_gender() -> None:
    tags = ["heist", "interracial relationship", "woman director", "east asian lead"]
    movies = [M("src", HEIST, keywords=tags), M("result", HEIST, keywords=tags)]
    movies += _filler()
    index = make_index(movies)
    reasons = explain(index, index.row["result"], [index.row["src"]])
    assert reasons.keywords == ["heist"]
