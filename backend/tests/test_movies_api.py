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
    assert body["keywords"] == [] and body["poster_url"] is None  # not enriched in fixtures


def test_detail_404(client: TestClient) -> None:
    assert client.get("/api/movies/tt9999999").status_code == 404


def _make_pickable(session: Session, *imdb_ids: str) -> None:
    from sqlalchemy import update

    from app.models import Movie

    session.execute(
        update(Movie)
        .where(Movie.imdb_id.in_(imdb_ids))
        .values(imdb_votes=30_000, poster_path="/p.jpg")
    )
    session.commit()


def _roll(client: TestClient, **params: str) -> list[tuple[str, str]]:
    resp = client.get("/api/movies/roll", params=params)
    assert resp.status_code == 200
    return [(r["genre"], r["movie"]["title"]) for r in resp.json()]


def test_roll_only_picks_well_rated_movies_with_posters(
    client: TestClient, session: Session
) -> None:
    assert _roll(client, genres="Crime") == []  # fixtures: few votes, no posters
    _make_pickable(session, "tt0000006", "tt0000004")  # The Godfather 9.2; tt0000004 is 5.0
    assert _roll(client, genres="Crime,Drama") == [("Crime", "The Godfather")]


def test_roll_one_per_genre_in_order(client: TestClient, session: Session) -> None:
    _make_pickable(session, "tt0000001", "tt0000006", "tt0000010")  # Heat, Godfather, Amélie
    for _ in range(5):
        rolled = _roll(client, genres="Romance,Crime,Drama,Western")
        assert [g for g, _ in rolled] == ["Romance", "Crime", "Drama"]  # no Westerns
        assert rolled[0] == ("Romance", "Amélie")
        assert {rolled[1][1], rolled[2][1]} == {"Heat", "The Godfather"}  # never twice


def test_roll_skips_recent_until_used_up(client: TestClient, session: Session) -> None:
    _make_pickable(session, "tt0000001", "tt0000006")
    assert _roll(client, genres="Crime", exclude="tt0000001") == [("Crime", "The Godfather")]
    # Everything excluded: the rotation starts over rather than leaving a gap.
    assert len(_roll(client, genres="Crime", exclude="tt0000001,tt0000006")) == 1


def test_roll_several_per_genre(client: TestClient, session: Session) -> None:
    _make_pickable(session, "tt0000001", "tt0000006", "tt0000010")  # Heat, Godfather, Amélie
    rolled = _roll(client, genres="Crime,Comedy", per_genre="2")
    assert [g for g, _ in rolled] == ["Crime", "Crime", "Comedy"]  # only one pickable Comedy
    assert {t for _, t in rolled[:2]} == {"Heat", "The Godfather"}
    # Recent ones are skipped first, then repeats fill the gap.
    rolled = _roll(client, genres="Crime", per_genre="2", exclude="tt0000001")
    assert sorted(t for _, t in rolled) == ["Heat", "The Godfather"]


def test_roll_validation(client: TestClient) -> None:
    assert client.get("/api/movies/roll").status_code == 422
    assert client.get("/api/movies/roll", params={"genres": ""}).status_code == 422
    bad = {"genres": "Crime", "per_genre": 5}
    assert client.get("/api/movies/roll", params=bad).status_code == 422
