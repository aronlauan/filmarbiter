from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, update

from app.api.letterboxd import get_letterboxd_source, get_verify_cache
from app.db import get_engine
from app.letterboxd import service
from app.letterboxd.client import (
    LetterboxdError,
    LoggedFilm,
    MemberMatch,
    PrivateProfileError,
    Profile,
    UserNotFoundError,
)
from app.main import app
from app.models import LetterboxdImport
from app.recommender.index import MovieIndex
from app.recommender.state import get_index

ALICE_FILMS = [
    # Fixture catalog: tt1 Heat, tt2 The Heat, tt6 The Godfather, tt7 Godfather (2022),
    # tt9 He Said "Hi", tt10 Amélie.
    LoggedFilm("heat-1995", "Heat", 1995, 5.0, True),
    LoggedFilm("the-godfather", "The Godfather", 1972, 4.5, False),
    LoggedFilm("amelie", "Amélie", 2001, 1.5, False),
    LoggedFilm("some-short", "Some Short Film", 2019, 4.0, False),  # not in catalog
    LoggedFilm("watched-only", "Unrated Thing", 2020, None, False),  # not in catalog
]


MEMBERS = [
    MemberMatch("alicefilms", "Alice", None, None),
    MemberMatch("alice", "Alice Liddell", "https://img/alice.jpg", "Pro"),
    MemberMatch("malice", "Malice Aforethought", None, "Patron"),
    MemberMatch("alice", "Alice Liddell", "https://img/alice.jpg", "Pro"),  # duplicate row
]


class FakeLetterboxd:
    def __init__(self) -> None:
        self.profile_calls = 0
        self.page_size = 2
        self.fail_pages = False
        self.search_queries: list[str] = []

    def profile(self, username: str) -> Profile:
        self.profile_calls += 1
        if username == "ghost":
            raise UserNotFoundError("404")
        if username == "secret":
            raise PrivateProfileError("403")
        if username == "flaky":
            raise LetterboxdError("cloudflare")
        return Profile(username.lower(), username.title(), None, len(ALICE_FILMS))

    def search_members(self, query: str, limit: int) -> list[MemberMatch]:
        self.search_queries.append(query)
        if query == "flaky":
            raise LetterboxdError("cloudflare")
        # Crude stand-in for Letterboxd's fuzzy search: substring on either field.
        return [m for m in MEMBERS if query in m.username or query in m.display_name.casefold()][
            :limit
        ]

    def film_pages(self, username: str) -> Iterator[list[LoggedFilm]]:
        if self.fail_pages:
            raise LetterboxdError("blocked")
        for i in range(0, len(ALICE_FILMS), self.page_size):
            yield ALICE_FILMS[i : i + self.page_size]

    def film_imdb_id(self, slug: str) -> str | None:
        return None


@pytest.fixture
def fake() -> FakeLetterboxd:
    return FakeLetterboxd()


@pytest.fixture
def lb(
    client: TestClient, catalog: Engine, index: MovieIndex, fake: FakeLetterboxd
) -> Iterator[TestClient]:
    cache = service.VerifyCache()
    app.dependency_overrides.update(
        {
            get_letterboxd_source: lambda: fake,
            get_verify_cache: lambda: cache,
            get_engine: lambda: catalog,
            get_index: lambda: index,
        }
    )
    yield client
    for dep in (get_letterboxd_source, get_verify_cache, get_engine, get_index):
        app.dependency_overrides.pop(dep, None)


# --- search -----------------------------------------------------------------


def _usernames(resp: dict) -> list[str]:
    return [r["username"] for r in resp["results"]]


def test_search_exact_matches_only_username_first(lb: TestClient, fake: FakeLetterboxd) -> None:
    resp = lb.get("/api/letterboxd/search", params={"q": "  @ALICE "})
    assert resp.status_code == 200
    body = resp.json()
    assert body["match"] == "exact"
    # "alice" (username) before "alicefilms" (display name "Alice"); "malice" dropped.
    assert _usernames(body) == ["alice", "alicefilms"]
    assert body["results"][0] == {
        "username": "alice",
        "display_name": "Alice Liddell",
        "avatar_url": "https://img/alice.jpg",
        "badge": "Pro",
    }
    assert fake.search_queries == ["alice"]


def test_search_display_name_with_spaces_is_exact(lb: TestClient) -> None:
    body = lb.get("/api/letterboxd/search", params={"q": "alice  liddell"}).json()
    assert body["match"] == "exact"
    assert _usernames(body) == ["alice"]


def test_search_falls_back_to_partial(lb: TestClient) -> None:
    body = lb.get("/api/letterboxd/search", params={"q": "lic"}).json()
    assert body["match"] == "partial"
    assert _usernames(body) == ["alicefilms", "alice", "malice"]  # deduped, rank kept


def test_search_no_results(lb: TestClient) -> None:
    body = lb.get("/api/letterboxd/search", params={"q": "zzz"}).json()
    assert body == {"query": "zzz", "match": "none", "results": []}


def test_search_blank_never_calls_letterboxd(lb: TestClient, fake: FakeLetterboxd) -> None:
    body = lb.get("/api/letterboxd/search", params={"q": " @ "}).json()
    assert body["match"] == "none"
    assert fake.search_queries == []
    assert lb.get("/api/letterboxd/search", params={"q": ""}).status_code == 422


def test_search_unavailable_is_503(lb: TestClient) -> None:
    assert lb.get("/api/letterboxd/search", params={"q": "flaky"}).status_code == 503


# --- verify -----------------------------------------------------------------


def test_verify_ok_and_cached(lb: TestClient, fake: FakeLetterboxd) -> None:
    for _ in range(2):
        resp = lb.get("/api/letterboxd/verify/Alice")
        assert resp.status_code == 200
        assert resp.json() == {
            "status": "ok",
            "profile": {
                "username": "alice",
                "display_name": "Alice",
                "avatar_url": None,
                "films_count": 5,
            },
        }
    assert fake.profile_calls == 1  # second call served from the cache


@pytest.mark.parametrize(("username", "status"), [("ghost", "not_found"), ("secret", "private")])
def test_verify_missing_or_private(lb: TestClient, username: str, status: str) -> None:
    resp = lb.get(f"/api/letterboxd/verify/{username}")
    assert resp.status_code == 200
    assert resp.json() == {"status": status, "profile": None}


@pytest.mark.parametrize("username", ["has space", "dash-name", "x" * 31, "emoji😀"])
def test_verify_invalid_format_never_calls_letterboxd(
    lb: TestClient, fake: FakeLetterboxd, username: str
) -> None:
    resp = lb.get(f"/api/letterboxd/verify/{username}")
    assert resp.json() == {"status": "invalid", "profile": None}
    assert fake.profile_calls == 0


def test_verify_unavailable_is_503(lb: TestClient) -> None:
    resp = lb.get("/api/letterboxd/verify/flaky")
    assert resp.status_code == 503
    assert resp.json()["detail"]["reason"] == "letterboxd_unavailable"


# --- import + recommendations ---------------------------------------------


def test_import_requires_verification(lb: TestClient) -> None:
    resp = lb.post("/api/letterboxd/import", json={"username": "alice"})
    assert resp.status_code == 409
    assert resp.json()["detail"]["reason"] == "not_verified"


def test_full_flow(lb: TestClient) -> None:
    lb.get("/api/letterboxd/verify/alice")

    # TestClient runs background tasks before returning, so the job is done here.
    resp = lb.post("/api/letterboxd/import", json={"username": "alice"})
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]

    status = lb.get(f"/api/letterboxd/import/{job_id}").json()
    assert status["status"] == "done"
    assert (status["films_total"], status["films_fetched"]) == (5, 5)
    assert (status["films_matched"], status["films_rated"]) == (3, 4)
    assert status["created_at"].endswith("Z") or status["created_at"].endswith("+00:00")

    rec = lb.get("/api/letterboxd/alice/recommendations", params={"limit": 3})
    assert rec.status_code == 200
    body = rec.json()
    assert (body["films_logged"], body["films_matched"]) == (5, 3)
    ids = [r["movie"]["imdb_id"] for r in body["results"]]
    assert len(ids) == 3
    assert not {"tt0000001", "tt0000006", "tt0000010"} & set(ids)  # logged films excluded
    for r in body["results"]:
        assert r["because"], "each pick cites films the user liked"
        for b in r["because"]:
            assert b["imdb_id"] != "tt0000010"  # Amélie was rated below their average
    heat = next(b for r in body["results"] for b in r["because"] if b["imdb_id"] == "tt0000001")
    assert heat == {
        "imdb_id": "tt0000001",
        "title": "Heat",
        "year": 1995,
        "rating": 5.0,
        "liked": True,
    }


def test_recent_import_is_reused_unless_refreshed(lb: TestClient) -> None:
    lb.get("/api/letterboxd/verify/alice")
    first = lb.post("/api/letterboxd/import", json={"username": "alice"}).json()["job_id"]

    again = lb.post("/api/letterboxd/import", json={"username": "ALICE"})
    assert again.status_code == 200 and again.json()["job_id"] == first

    fresh = lb.post("/api/letterboxd/import", json={"username": "alice", "refresh": True})
    assert fresh.status_code == 202 and fresh.json()["job_id"] != first


def test_failed_import_reports_reason(lb: TestClient, fake: FakeLetterboxd) -> None:
    fake.fail_pages = True
    lb.get("/api/letterboxd/verify/alice")
    job_id = lb.post("/api/letterboxd/import", json={"username": "alice"}).json()["job_id"]
    status = lb.get(f"/api/letterboxd/import/{job_id}").json()
    assert (status["status"], status["error"]) == ("failed", "letterboxd_unavailable")
    # A failed import doesn't block retrying.
    fake.fail_pages = False
    retry = lb.post("/api/letterboxd/import", json={"username": "alice"})
    assert retry.status_code == 202


def test_stale_running_job_is_replaced(lb: TestClient, catalog: Engine) -> None:
    lb.get("/api/letterboxd/verify/alice")
    job_id = lb.post("/api/letterboxd/import", json={"username": "alice"}).json()["job_id"]
    # Simulate a server restart mid-import an hour ago.
    an_hour_ago = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=1)
    with catalog.begin() as c:
        c.execute(
            update(LetterboxdImport)
            .where(LetterboxdImport.id == job_id)
            .values(status="running", created_at=an_hour_ago, finished_at=None)
        )
    resp = lb.post("/api/letterboxd/import", json={"username": "alice"})
    assert resp.status_code == 202 and resp.json()["job_id"] != job_id
    old = lb.get(f"/api/letterboxd/import/{job_id}").json()
    assert (old["status"], old["error"]) == ("failed", "interrupted")


def test_unknown_job_and_not_imported(lb: TestClient) -> None:
    assert lb.get("/api/letterboxd/import/nope").status_code == 404
    resp = lb.get("/api/letterboxd/bob/recommendations")
    assert resp.status_code == 404
    assert resp.json()["detail"]["reason"] == "not_imported"
