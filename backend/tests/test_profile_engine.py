import numpy as np
import pytest

from app.recommender.engine import (
    LIKE_BONUS,
    NEGATIVE_SCALE,
    RatedFilm,
    profile_weights,
    recommend_for_profile,
)
from tests.test_engine import ANIMATION, HEIST, M, make_index


def test_weights_are_centered_on_the_users_mean() -> None:
    films = [RatedFilm("a", 5.0), RatedFilm("b", 3.0), RatedFilm("c", 1.0)]  # mean 3.0
    assert profile_weights(films).tolist() == pytest.approx([2.0, 0.0, -2.0 * NEGATIVE_SCALE])


def test_likes_add_a_bonus_and_unrated_films_are_neutral() -> None:
    films = [RatedFilm("a", 4.0), RatedFilm("b", 2.0), RatedFilm("c", None, liked=True)]
    assert profile_weights(films).tolist() == pytest.approx(
        [1.0, -1.0 * NEGATIVE_SCALE, LIKE_BONUS]
    )


@pytest.mark.parametrize(
    "films",
    [
        [RatedFilm("a", 4.0), RatedFilm("b", 4.0)],  # all the same rating
        [RatedFilm("a", None), RatedFilm("b", None)],  # nothing rated
    ],
)
def test_weights_fall_back_to_equal_when_there_is_no_signal(films: list[RatedFilm]) -> None:
    assert profile_weights(films).tolist() == [1.0, 1.0]


def _index():
    return make_index(
        [
            M("h1", HEIST),
            M("h2", HEIST, overview="thieves plan a bank heist in the city"),
            M("h3", HEIST, overview="a crew of thieves pulls one last bank heist"),
            M("h4", HEIST, overview="a getaway driver and a crew rob a bank"),
            M("a1", ANIMATION),
            M("a2", ANIMATION, overview="toys come alive on an adventure"),
            M("a3", ANIMATION, overview="a robot and a toy go on an adventure"),
        ]
    )


def test_recommends_toward_loved_and_away_from_disliked() -> None:
    films = [
        RatedFilm("h1", 5.0),
        RatedFilm("h2", 4.5, liked=True),
        RatedFilm("a1", 1.0),
    ]
    results = recommend_for_profile(_index(), films, k=3)
    ids = [r.imdb_id for r in results]
    assert set(ids[:2]) == {"h3", "h4"}
    assert not {"h1", "h2", "a1"} & set(ids)  # never recommend logged films
    assert all(i not in ids[:2] for i in ("a2", "a3"))
    # "Because you liked" only cites positively weighted films, never the disliked one.
    for r in results:
        assert r.because and "a1" not in r.because
        assert set(r.because) <= {"h1", "h2"}


def test_scores_are_sorted_and_unknown_films_ignored() -> None:
    films = [RatedFilm("h1", 5.0), RatedFilm("not-in-catalog", 5.0), RatedFilm("a1", 2.0)]
    results = recommend_for_profile(_index(), films, k=4)
    scores = [r.score for r in results]
    assert scores == sorted(scores, reverse=True)
    assert len(results) == 4


def test_no_known_films_returns_nothing() -> None:
    assert recommend_for_profile(_index(), [RatedFilm("nope", 5.0)]) == []


def test_profile_is_a_unit_vector_of_weighted_films() -> None:
    # Sanity: a single loved film behaves like blending that film alone.
    index = _index()
    (top,) = recommend_for_profile(index, [RatedFilm("h1", 5.0)], k=1)
    sims = index.matrix @ index.matrix[index.row["h1"]]
    sims[index.row["h1"]] = -np.inf
    assert top.imdb_id in {index.ids[i] for i in np.argsort(-sims)[:2]}


def test_because_films_vary_across_results() -> None:
    # Five loved heist films; without the repeat penalty every pick would cite the
    # same top-weighted favorites.
    loved = [
        M(f"l{i}", HEIST, overview=f"a crew plans heist number {i} in city {i}") for i in range(5)
    ]
    candidates = [
        M(f"c{i}", HEIST, overview=f"thieves plan a daring heist in town {i}") for i in range(4)
    ]
    index = make_index(loved + candidates + [M("a1", ANIMATION)])
    films = [RatedFilm(f"l{i}", 5.0 if i == 0 else 4.5) for i in range(5)]
    films.append(RatedFilm("a1", 1.0))
    results = recommend_for_profile(index, films, k=3)
    cited = [b for r in results for b in r.because]
    assert len(set(cited)) > 3
