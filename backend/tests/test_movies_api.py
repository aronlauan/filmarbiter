from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.search import search_titles


def _titles(session: Session, q: str) -> list[str]:
    return [m.title for m in search_titles(session, q)]


def test_search_prefix_and_popularity(session: Session) -> None:
    assert _titles(session, "hea") == ["Heat", "The Heat"]  # by votes


def test_search_exact_match_ignores_leading_article(session: Session) -> None:
    # 'Godfather' (2022) is a literal exact match, but 'The Godfather' also counts as
    # exact and has far more votes, so it wins.
    assert _titles(session, "godfather") == ["The Godfather", "Godfather"]
    assert _titles(session, "the godfather")[0] == "The Godfather"


def test_search_accents_and_original_title(session: Session) -> None:
    assert _titles(session, "amelie") == ["Amélie"]
    assert _titles(session, "fabuleux destin") == ["Amélie"]


def test_search_ignores_punctuation_only(session: Session) -> None:
    assert _titles(session, '"*!') == []


def test_search_endpoint(client: TestClient) -> None:
    resp = client.get("/api/movies/search", params={"q": "heat", "limit": 1})
    assert resp.status_code == 200
    assert resp.json() == [
        {"imdb_id": "tt0000001", "title": "Heat", "year": 1995, "poster_url": None}
    ]


def test_search_endpoint_validation(client: TestClient) -> None:
    assert client.get("/api/movies/search", params={"q": ""}).status_code == 422
    assert client.get("/api/movies/search", params={"q": "x", "limit": 99}).status_code == 422


def test_detail_endpoint(client: TestClient) -> None:
    resp = client.get("/api/movies/tt0000006")
    assert resp.status_code == 200
    body = resp.json()
    assert body["title"] == "The Godfather"
    assert body["original_title"] is None  # same as title
    assert body["genres"] == ["Crime", "Drama"]
    assert [p["name"] for p in body["directors"]] == ["Francis Ford Coppola"]
    assert [p["name"] for p in body["writers"]] == ["Mario Puzo", "Francis Ford Coppola"]
    assert [p["name"] for p in body["cast"]] == ["Marlon Brando", "Al Pacino"]
    assert body["imdb_url"] == "https://www.imdb.com/title/tt0000006/"


def test_detail_404(client: TestClient) -> None:
    assert client.get("/api/movies/tt9999999").status_code == 404
