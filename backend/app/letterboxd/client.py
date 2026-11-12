"""Thin wrapper around letterboxdpy (a scraper; Letterboxd has no open API).

Everything Letterboxd-specific lives here so it can be swapped for a CSV-export
upload or the official API later. Library exceptions are translated into our
own three: user not found, private, or Letterboxd unavailable.
"""

import re
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Protocol

USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{1,30}$")
DOMAIN = "https://letterboxd.com"
FILMS_PER_PAGE = 72


class LetterboxdError(Exception):
    reason = "letterboxd_unavailable"


class UserNotFoundError(LetterboxdError):
    reason = "not_found"


class PrivateProfileError(LetterboxdError):
    reason = "private"


@dataclass(frozen=True)
class Profile:
    username: str
    display_name: str
    avatar_url: str | None
    films_count: int


@dataclass(frozen=True)
class MemberMatch:
    """One account from Letterboxd's member search (no film count; that needs the profile)."""

    username: str
    display_name: str
    avatar_url: str | None
    badge: str | None  # "Pro" / "Patron" / None


@dataclass(frozen=True)
class LoggedFilm:
    slug: str
    name: str
    year: int | None
    rating: float | None  # 0.5..5 stars
    liked: bool


class LetterboxdSource(Protocol):
    def profile(self, username: str) -> Profile: ...
    def search_members(self, query: str, limit: int) -> list[MemberMatch]: ...
    def film_pages(self, username: str) -> Iterator[list[LoggedFilm]]: ...
    def film_imdb_id(self, slug: str) -> str | None: ...


def valid_username(username: str) -> bool:
    return bool(USERNAME_RE.match(username))


def _translate[T](fn: Callable[[], T]) -> T:
    from letterboxdpy.core.exceptions import (
        AccessDeniedError,
        PrivateRouteError,
        ResourceNotFoundError,
    )

    try:
        return fn()
    except ResourceNotFoundError as e:
        raise UserNotFoundError(str(e)) from e
    except PrivateRouteError as e:
        raise PrivateProfileError(str(e)) from e
    except AccessDeniedError as e:  # Cloudflare / IP block
        raise LetterboxdError(str(e)) from e
    except Exception as e:  # network errors, 5xx, markup changes the parser can't handle
        raise LetterboxdError(f"{type(e).__name__}: {e}") from e


class LetterboxdClient:
    """Real implementation. Sleeps `delay` seconds between page requests."""

    def __init__(self, delay: float = 0.25) -> None:
        self.delay = delay

    def profile(self, username: str) -> Profile:
        from letterboxdpy.pages.user_profile import UserProfile

        def load() -> Profile:
            p = UserProfile(username.lower())  # one request: the profile page
            stats = p.get_stats() or {}
            avatar = p.get_avatar() or {}
            return Profile(
                username=username.lower(),
                display_name=p.get_display_name() or username,
                avatar_url=avatar.get("url") if avatar.get("exists", True) else None,
                films_count=int(stats.get("films", 0)),
            )

        return _translate(load)

    def search_members(self, query: str, limit: int) -> list[MemberMatch]:
        """Letterboxd's own member search: fuzzy over usernames and display names."""
        from letterboxdpy.search import Search, SearchFilter

        def load() -> list[MemberMatch]:
            raw = Search(query, SearchFilter.MEMBERS).get_results(limit)
            return [
                MemberMatch(
                    username=r["username"].lower(),
                    display_name=r.get("display_name") or r["username"],
                    avatar_url=(r.get("avatar") or {}).get("url")
                    if (r.get("avatar") or {}).get("exists")
                    else None,
                    badge=r.get("badge"),
                )
                for r in raw.get("results", [])
                if r.get("username")
            ]

        return _translate(load)

    def film_pages(self, username: str) -> Iterator[list[LoggedFilm]]:
        from letterboxdpy.core.scraper import parse_url
        from letterboxdpy.pages.user_films import extract_movies_from_user_watched
        from letterboxdpy.utils.utils_url import get_page_url

        base = f"{DOMAIN}/{username.lower()}/films/"
        page = 0
        while True:
            page += 1
            url = get_page_url(base, page)
            raw = _translate(lambda url=url: extract_movies_from_user_watched(parse_url(url)))
            films = [
                LoggedFilm(
                    slug=f["slug"],
                    name=f["name"],
                    year=f.get("year"),
                    rating=f.get("rating"),
                    liked=bool(f.get("liked")),
                )
                for f in raw.values()
                if f.get("slug")
            ]
            yield films
            if len(raw) < FILMS_PER_PAGE:
                return
            time.sleep(self.delay)

    def film_imdb_id(self, slug: str) -> str | None:
        from letterboxdpy.pages.movie_profile import MovieProfile

        time.sleep(self.delay)
        try:
            return _translate(lambda: MovieProfile(slug).get_imdb_id())
        except UserNotFoundError:  # film page 404s
            return None
