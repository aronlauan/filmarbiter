from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, insert, update

from app.main import app
from app.models import Movie, MovieKeyword
from app.recommender.features import BlockWeights
from app.recommender.index import MovieIndex
from app.recommender.state import get_index
from ingest.build_vectors import build
from tests.conftest import fake_embed


@pytest.fixture
def index(catalog: Engine, tmp_path: Path) -> MovieIndex:
    """Vectors built from the fixture catalog, saved and loaded like production."""
    with catalog.begin() as conn:
        for imdb_id, overview, coll in [
            ("tt0000001", "a master thief plans one last heist", None),
            ("tt0000002", "two cops investigate a drug lord", None),
            ("tt0000006", "the aging patriarch of a crime dynasty", 230),
            ("tt0000007", "a crime family patriarch hands over power", 230),
        ]:
            conn.execute(
                update(Movie)
                .where(Movie.imdb_id == imdb_id)
                .values(overview=overview, collection_id=coll, original_language="en")
            )
        conn.execute(
            insert(MovieKeyword),
            [
                {"imdb_id": "tt0000001", "keyword_id": 1, "name": "heist"},
                {"imdb_id": "tt0000001", "keyword_id": 2, "name": "sequel"},  # ignored tag
                {"imdb_id": "tt0000002", "keyword_id": 1, "name": "heist"},
                {"imdb_id": "tt0000002", "keyword_id": 2, "name": "sequel"},
            ],
        )
    path = tmp_path / "vectors.npz"
    meta = build(catalog, path, fake_embed, BlockWeights())
    assert meta["movies"] == 6 and path.with_suffix(".json").exists()
    return MovieIndex.load(catalog, path)


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
