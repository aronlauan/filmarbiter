import numpy as np
import pytest

from app.recommender.features import (
    BlockWeights,
    MovieFeatures,
    build_matrix,
    era_block,
)
from tests.conftest import fake_embed

W = BlockWeights()


def _movie(i: str, **kw) -> MovieFeatures:
    base = dict(
        overview="a master thief plans one last bank heist",
        keywords=["heist", "bank robbery", "neo-noir"],
        genres=["Crime", "Drama"],
        people=[("nm1", "director", 0), ("nm2", "cast", 0)],
        year=1995,
        language="en",
    )
    base.update(kw)
    return MovieFeatures(imdb_id=i, **base)


def _filler(n: int) -> list[MovieFeatures]:
    """Unrelated movies so TF-IDF has a realistic background (and people/keywords
    on the test movies appear in >= 2 movies)."""
    return [
        MovieFeatures(
            imdb_id=f"f{i}",
            overview=f"filler story number {i} about gardens",
            keywords=[f"tag{i % 7}", f"tag{i % 5 + 10}"],
            genres=["Comedy"] if i % 2 else ["Romance"],
            people=[(f"p{i % 6}", "cast", 0)],
            year=1960 + i,
            language="fr" if i % 3 else "en",
        )
        for i in range(30)
    ]


def _sim(m: np.ndarray, a: int, b: int) -> float:
    return float(m[a] @ m[b])


def test_rows_are_unit_length() -> None:
    m, _ = build_matrix([_movie("a"), _movie("b", keywords=[])] + _filler(30), fake_embed)
    assert np.allclose(np.linalg.norm(m, axis=1), 1.0, atol=1e-5)


def test_similarity_is_weighted_sum_of_block_similarities() -> None:
    movies = [_movie("a"), _movie("b", year=2005, overview="a crew plans a heist")]
    m, slices = build_matrix(movies + _filler(30), fake_embed)

    def block_cos(name: str) -> float:
        x, y = m[0, slices[name]], m[1, slices[name]]
        return float(x @ y / (np.linalg.norm(x) * np.linalg.norm(y)))

    expected = sum(getattr(W, name) * block_cos(name) for name in slices)
    assert _sim(m, 0, 1) == pytest.approx(expected, abs=1e-5)


def test_era_and_language_mismatch_costs_at_most_ten_percent() -> None:
    # Identical content; one is a 1950 Japanese film, the other a 2010 English one.
    movies = [_movie("a", year=2010, language="en"), _movie("b", year=1950, language="ja")]
    m, _ = build_matrix(movies + _filler(30), fake_embed)
    assert _sim(m, 0, 1) == pytest.approx(1.0 - W.era - W.language, abs=1e-3)


@pytest.mark.parametrize(("gap", "expected"), [(0, 1.0), (10, 0.68), (20, 0.21), (30, 0.03)])
def test_era_similarity_decays_smoothly(gap: int, expected: float) -> None:
    e = era_block([MovieFeatures("a", year=1990), MovieFeatures("b", year=1990 + gap)])
    e = e / np.linalg.norm(e, axis=1, keepdims=True)
    assert float(e[0] @ e[1]) == pytest.approx(expected, abs=0.01)


def test_missing_block_shares_score_among_remaining() -> None:
    # Same everything, but one has no keywords: remaining blocks share the score, so the
    # similarity is sqrt(1 - w_keywords), not capped at (1 - w_keywords).
    # ("c" also carries a's keywords; tags on only one movie are dropped by min_df=2.)
    c = _movie("c", overview="unrelated", genres=["Comedy"], people=[], year=1960)
    m, _ = build_matrix([_movie("a"), _movie("b", keywords=[]), c, *_filler(30)], fake_embed)
    assert _sim(m, 0, 1) == pytest.approx(np.sqrt(1 - W.keywords), abs=1e-3)


def test_rare_keywords_count_more_than_common_ones() -> None:
    common = [f"f{i}" for i in range(30)]
    filler = _filler(30)
    for f in filler:  # "murder" is everywhere; "heist" is rare
        f.keywords = [*f.keywords, "murder"]
    a = _movie("a", keywords=["heist", "murder"], overview=None, genres=[], people=[])
    b = _movie("b", keywords=["heist"], overview=None, genres=[], people=[])
    c = _movie("c", keywords=["murder"], overview=None, genres=[], people=[])
    m, _ = build_matrix([a, b, c, *filler], fake_embed)
    assert common  # filler present
    assert _sim(m, 0, 1) > _sim(m, 0, 2)


def test_shared_director_increases_similarity() -> None:
    same = _movie("b", people=[("nm1", "director", 0)], overview="something else entirely")
    other = _movie("c", people=[("nm9", "director", 0)], overview="something else entirely")
    extra = _movie("d", people=[("nm9", "director", 0)])  # nm9 needs >= 2 films
    m, _ = build_matrix([_movie("a"), same, other, extra, *_filler(30)], fake_embed)
    assert _sim(m, 0, 1) > _sim(m, 0, 2)
