from collections.abc import Iterator
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from app.main import app
from app.recommender.index import MovieIndex
from app.recommender.movie_map import (
    GRID,
    MovieMap,
    layout,
    name_sections,
    neighbor_edges,
    place_on_grid,
)
from app.recommender.state import get_map
from ingest.build_map import build


def test_layout_shape_and_range() -> None:
    rng = np.random.default_rng(0)
    # Two well-separated clusters should stay separated in 2D.
    a = rng.normal(0, 0.05, (20, 16)) + 1.0
    b = rng.normal(0, 0.05, (20, 16)) - 1.0
    xy = layout(np.vstack([a, b]).astype(np.float32))
    assert xy.shape == (40, 2)
    assert np.abs(xy).max() <= 1.0
    within = np.linalg.norm(xy[:20] - xy[:20].mean(0), axis=1).mean()
    between = np.linalg.norm(xy[:20].mean(0) - xy[20:].mean(0))
    assert between > 3 * within


def test_layout_tiny_input() -> None:
    assert layout(np.ones((2, 4), dtype=np.float32)).shape == (2, 2)


def test_place_on_grid_keeps_pads_apart() -> None:
    g = 0.1
    # Same spot twice: the second pad moves 2 cells away (one free cell between).
    cells = place_on_grid(np.array([[0.0, 0.0], [0.0, 0.0]]), grid=g, reach=3)
    assert cells[0] == (0, 0)
    assert cells[1] is not None and max(abs(cells[1][0]), abs(cells[1][1])) == 2
    # No room within reach: left off the board.
    crowd = place_on_grid(np.zeros((10, 2)), grid=g, reach=1)
    assert crowd[0] == (0, 0) and crowd[1:] == [None] * 9
    # Far-apart points stay at their own nearest cell.
    assert place_on_grid(np.array([[0.31, 0.0], [-0.52, 0.2]]), grid=g) == [(3, 0), (-5, 2)]


def test_place_on_grid_leaves_aisles_between_sections() -> None:
    g = 0.1
    # Same spot, different sections: the second seat keeps an aisle's distance away.
    pts = np.array([[0.0, 0.0], [0.0, 0.0], [0.0, 0.0]])
    cells = place_on_grid(pts, np.array([0, 0, 1]), grid=g, reach=6, aisle=3)
    assert cells[0] == (0, 0)
    assert cells[1] is not None and max(map(abs, cells[1])) == 2  # same section: one free cell
    assert cells[2] is not None and max(map(abs, cells[2])) >= 4  # other section: 3-cell aisle
    # Not enough reach to clear the aisle: no seat.
    assert place_on_grid(pts[:2], np.array([0, 1]), grid=g, reach=3, aisle=3)[1] is None


def test_name_sections() -> None:
    # Drama everywhere, so it never names a section; repeated wants get resolved.
    labels = np.array([0] * 10 + [1] * 10 + [2] * 10)
    genres = (
        [["Horror", "Drama"]] * 10
        + [["Horror", "Thriller", "Drama"]] * 10
        + [["Animation", "Drama"]] * 10
    )
    names = name_sections(labels, genres)
    assert names[2] == "ANIMATION"
    assert sorted([names[0], names[1]]) == ["HORROR", "THRILLERS"]


def test_name_sections_compound() -> None:
    # A mixed section: half comedies, half dramas (Drama also fills the other section,
    # so Comedy is the distinctive one). One name would fit only half the films.
    labels = np.array([0] * 10 + [1] * 10)
    genres = [["Comedy"]] * 5 + [["Drama"]] * 5 + [["Drama", "War"]] * 10
    assert name_sections(labels, genres)[0] == "COMEDY & DRAMA"
    # A section its name already fits well stays one word.
    assert name_sections(labels, genres)[1] == "WAR"


def test_name_sections_fallback() -> None:
    # One section only: every genre has lift 1; the best one still names it.
    assert name_sections(np.zeros(5, dtype=np.int64), [["Comedy"]] * 5) == {0: "COMEDY"}


def test_neighbor_edges(index: MovieIndex) -> None:
    edges = neighbor_edges(index.ids, index, k=1)
    assert all(i < j for i, j in edges)
    ids = index.ids
    pairs = {frozenset((ids[i], ids[j])) for i, j in edges}
    assert frozenset(("tt0000001", "tt0000002")) in pairs  # shared heist overview + keyword


@pytest.fixture
def movie_map(catalog: Engine, index: MovieIndex, tmp_path: Path) -> MovieMap:
    vectors = tmp_path / "vectors.npz"  # written by the index fixture
    out = tmp_path / "map.npz"
    meta = build(vectors, out)
    assert meta["movies"] == len(index) and out.with_suffix(".json").exists()
    return MovieMap.load(catalog, out, index, candidates=4)


@pytest.fixture
def map_client(client: TestClient, movie_map: MovieMap) -> Iterator[TestClient]:
    app.dependency_overrides[get_map] = lambda: movie_map
    yield client
    app.dependency_overrides.pop(get_map, None)


def test_map_endpoint(map_client: TestClient, movie_map: MovieMap) -> None:
    resp = map_client.get("/api/map")
    assert resp.status_code == 200
    body = resp.json()
    assert body["grid"] == GRID
    assert 1 <= len(body["nodes"]) <= 4  # at most `candidates`, most-voted first
    votes_order = [n["imdb_id"] for n in body["nodes"]]
    assert votes_order == [n.imdb_id for n in movie_map.nodes]
    node = body["nodes"][0]
    assert {"imdb_id", "title", "year", "poster_url", "x", "y", "section", "genres"} <= node.keys()
    assert body["sections"] and all(
        0 <= n["section"] < len(body["sections"]) for n in body["nodes"]
    )
    assert sum(sec["size"] for sec in body["sections"]) == len(body["nodes"])
    assert all(0 <= i < j < 4 for i, j in body["edges"])


def test_map_seats(map_client: TestClient, movie_map: MovieMap) -> None:
    seated = {n.imdb_id for n in movie_map.nodes}
    hidden = [i for i in movie_map.ids if i not in seated]
    assert len(hidden) >= 2
    seat_one = movie_map.nodes[0].imdb_id
    query = ",".join([hidden[0], "tt9999999", seat_one, hidden[1], hidden[0]])
    resp = map_client.get(f"/api/map/seats?ids={query}")
    assert resp.status_code == 200
    body = resp.json()
    # Only movies without a seat, once each, in request order.
    assert [s["imdb_id"] for s in body] == hidden[:2]
    cells = [(round(n.x / GRID), round(n.y / GRID)) for n in movie_map.nodes]
    for extra in body:
        cell = (round(extra["x"] / GRID), round(extra["y"] / GRID))
        # A real seat: on the grid, clear of every other seat, in a section, linked.
        assert all(max(abs(cell[0] - c[0]), abs(cell[1] - c[1])) >= 2 for c in cells)
        cells.append(cell)
        assert 0 <= extra["section"] < len(movie_map.sections)
        assert extra["links"] and all(0 <= i < len(movie_map.nodes) for i in extra["links"])
        # The film's own genres, for the hover card.
        assert (
            extra["genres"]
            == movie_map.index.features[movie_map.index.row[extra["imdb_id"]]].genres
        )


def test_map_seats_are_stable(movie_map: MovieMap) -> None:
    hidden = [i for i in movie_map.ids if i not in {n.imdb_id for n in movie_map.nodes}]
    first = movie_map.extra_seats(hidden[:1])[0]
    again = movie_map.extra_seats(hidden[:2])[0]
    assert (first.x, first.y) == (again.x, again.y)  # adding more doesn't move earlier ones


def test_map_seats_limit(map_client: TestClient) -> None:
    ids = ",".join(f"tt{i:07d}" for i in range(21))
    assert map_client.get(f"/api/map/seats?ids={ids}").status_code == 422


def test_map_not_built(client: TestClient) -> None:
    assert client.get("/api/map").status_code == 503


def test_precomputed_sections_match(
    catalog: Engine, index: MovieIndex, movie_map: MovieMap, tmp_path: Path
) -> None:
    """build_map saves the sections so the API can skip scikit-learn; the result must
    be the same map as computing them at load."""
    out = tmp_path / "map_sections.npz"
    build(tmp_path / "vectors.npz", out, eng=catalog, candidates=4)
    with np.load(out) as npz:
        assert len(npz["section_ids"]) == len(npz["section_labels"]) > 0
    pre = MovieMap.load(catalog, out, index, candidates=4)
    assert pre.nodes == movie_map.nodes and pre.sections == movie_map.sections
    # Saved sections for a different candidate set are ignored, not misapplied.
    stale = MovieMap.load(catalog, out, index, candidates=3)
    assert len(stale.nodes) <= 3
