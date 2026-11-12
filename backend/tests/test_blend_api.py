from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.recommender.index import MovieIndex
from app.recommender.state import get_index


@pytest.fixture
def blend_client(client: TestClient, index: MovieIndex) -> Iterator[TestClient]:
    app.dependency_overrides[get_index] = lambda: index
    yield client
    app.dependency_overrides.pop(get_index, None)


def test_ignored_keywords_are_filtered(index: MovieIndex) -> None:
    assert index.keyword_sets[index.row["tt0000001"]] == {"heist"}


def test_blend_endpoint(blend_client: TestClient) -> None:
    resp = blend_client.post("/api/blend", json={"imdb_ids": ["tt0000001"]})
    assert resp.status_code == 200
    body = resp.json()
    assert [p["imdb_id"] for p in body["picks"]] == ["tt0000001"]
    assert len(body["results"]) == 3
    top = body["results"][0]
    assert top["movie"]["imdb_id"] == "tt0000002"  # shares "heist" + Action/Crime
    assert "heist" in top["reasons"]["keywords"]
    matches = [r["match"] for r in body["results"]]
    assert all(0 <= m <= 100 for m in matches)
    assert matches == sorted(matches, reverse=True)  # ranked by score, so by match too
    assert top["movie"]["letterboxd_url"] == "https://letterboxd.com/imdb/tt0000002/"
    assert "tt0000001" not in {r["movie"]["imdb_id"] for r in body["results"]}


def test_blend_excludes_same_collection(blend_client: TestClient) -> None:
    resp = blend_client.post("/api/blend", json={"imdb_ids": ["tt0000006"]})
    assert resp.status_code == 200
    assert "tt0000007" not in {r["movie"]["imdb_id"] for r in resp.json()["results"]}


def test_blend_unknown_movie(blend_client: TestClient) -> None:
    resp = blend_client.post("/api/blend", json={"imdb_ids": ["tt0000001", "tt9999999"]})
    assert resp.status_code == 404
    assert resp.json()["detail"] == {"unknown_imdb_ids": ["tt9999999"]}


@pytest.mark.parametrize("ids", [[], [f"tt000000{i}" for i in range(6)]])
def test_blend_pick_limits(blend_client: TestClient, ids: list[str]) -> None:
    assert blend_client.post("/api/blend", json={"imdb_ids": ids}).status_code == 422


def test_blend_without_vectors_is_503(client: TestClient) -> None:
    resp = client.post("/api/blend", json={"imdb_ids": ["tt0000001"]})
    assert resp.status_code == 503
