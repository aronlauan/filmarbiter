"""In-memory movie index: the vector matrix plus the per-movie metadata the
engine needs for scoring (quality, collection) and explanations (keywords,
genres, people)."""

import json
import logging
import math
import sys
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from sqlalchemy import Engine, select

from app.models import Movie, MovieKeyword, MoviePerson, Person
from app.recommender.features import IGNORED_KEYWORDS, MovieFeatures

log = logging.getLogger(__name__)

NO_COLLECTION = -1


def quality_scores(ratings: Sequence[float | None], votes: Sequence[int]) -> np.ndarray:
    """0..1 quality prior: Bayesian-average IMDb rating (shrunk toward the catalog
    mean for low-vote films), min-max scaled across the catalog."""
    r = np.array([x if x is not None else np.nan for x in ratings], dtype=np.float64)
    v = np.asarray(votes, dtype=np.float64)
    c = np.nanmean(r) if np.isfinite(r).any() else 0.0
    r = np.nan_to_num(r, nan=c)
    m = float(np.median(v)) if len(v) else 0.0
    bayes = (v * r + m * c) / (v + m) if m > 0 else r
    lo, hi = float(bayes.min(initial=0)), float(bayes.max(initial=0))
    return ((bayes - lo) / (hi - lo) if hi > lo else np.zeros_like(bayes)).astype(np.float32)


@dataclass
class MovieIndex:
    ids: list[str]
    matrix: np.ndarray  # N x D, unit rows
    quality: np.ndarray  # N, 0..1
    collection: np.ndarray  # N, int (NO_COLLECTION if none)
    features: list[MovieFeatures]
    person_names: dict[str, str]
    keyword_idf: dict[str, float]

    def __post_init__(self) -> None:
        self.row = {imdb_id: i for i, imdb_id in enumerate(self.ids)}
        self.keyword_sets = [set(f.keywords) for f in self.features]
        self.people_roles = [_best_roles(f.people) for f in self.features]

    def __len__(self) -> int:
        return len(self.ids)

    @classmethod
    def build(
        cls,
        features: list[MovieFeatures],
        matrix: np.ndarray,
        quality: np.ndarray,
        collection: Sequence[int | None],
        person_names: dict[str, str],
    ) -> "MovieIndex":
        df = Counter(k for f in features for k in set(f.keywords))
        n = max(len(features), 1)
        idf = {k: math.log(n / c) for k, c in df.items()}
        coll = np.array([c if c is not None else NO_COLLECTION for c in collection], dtype=np.int64)
        return cls(
            ids=[f.imdb_id for f in features],
            matrix=matrix.astype(np.float32, copy=False),
            quality=quality.astype(np.float32),
            collection=coll,
            features=features,
            person_names=person_names,
            keyword_idf=idf,
        )

    @classmethod
    def load(cls, eng: Engine, vectors_path: Path) -> "MovieIndex":
        """Load vectors saved by ingest/build_vectors.py and join DB metadata.
        Movies present in only one of the two (stale vectors) are skipped."""
        with np.load(vectors_path, allow_pickle=False) as npz:
            ids = [str(x) for x in npz["ids"]]
            matrix = npz["matrix"]
        meta = json.loads(vectors_path.with_suffix(".json").read_text())
        rows = {imdb_id: i for i, imdb_id in enumerate(ids)}

        # Plain row queries rather than ORM objects: loading ~19k movies with ~160k
        # credits and ~185k keywords as ORM instances peaked near 1 GB of RSS (it has
        # to fit a 512 MB host). Strings repeated across movies are interned.
        intern = sys.intern
        keywords: dict[str, list[str]] = defaultdict(list)
        people: dict[str, list[tuple[str, str, int]]] = defaultdict(list)
        with eng.connect() as conn:
            for imdb_id, name in conn.execute(
                select(MovieKeyword.imdb_id, MovieKeyword.name).order_by(
                    MovieKeyword.imdb_id, MovieKeyword.name
                )
            ):
                if name not in IGNORED_KEYWORDS:
                    keywords[imdb_id].append(intern(name))
            for imdb_id, nconst, role, ordering in conn.execute(
                select(
                    MoviePerson.imdb_id, MoviePerson.nconst, MoviePerson.role, MoviePerson.ordering
                ).order_by(MoviePerson.imdb_id, MoviePerson.ordering, MoviePerson.nconst)
            ):
                people[imdb_id].append((intern(nconst), intern(role), ordering))
            names = dict(
                conn.execute(
                    select(Person.nconst, Person.name).where(
                        Person.nconst.in_(select(MoviePerson.nconst).distinct())
                    )
                ).all()
            )
            movies = [
                m
                for m in conn.execute(
                    select(
                        Movie.imdb_id,
                        Movie.genres,
                        Movie.year,
                        Movie.original_language,
                        Movie.imdb_rating,
                        Movie.imdb_votes,
                        Movie.collection_id,
                    )
                )
                if m.imdb_id in rows
            ]
        if len(movies) < len(ids):
            log.warning("%d vectors have no catalog movie (stale)", len(ids) - len(movies))

        features = [
            MovieFeatures(
                imdb_id=m.imdb_id,
                # overview is only needed to build vectors; skipping it saves ~6 MB
                # of memory and of database transfer on every startup.
                keywords=keywords.get(m.imdb_id, []),
                genres=[intern(g) for g in m.genres.split(",")] if m.genres else [],
                people=people.get(m.imdb_id, []),
                year=m.year,
                language=m.original_language,
            )
            for m in movies
        ]
        del keywords, people
        index = cls.build(
            features,
            matrix[[rows[m.imdb_id] for m in movies]],
            quality_scores([m.imdb_rating for m in movies], [m.imdb_votes for m in movies]),
            [m.collection_id for m in movies],
            names,
        )
        log.info(
            "movie index: %d movies, %d dims, built %s",
            len(index),
            matrix.shape[1],
            meta.get("built_at"),
        )
        return index


def movie_features(m: Movie) -> MovieFeatures:
    return MovieFeatures(
        imdb_id=m.imdb_id,
        overview=m.overview,
        keywords=[k.name for k in m.keywords if k.name not in IGNORED_KEYWORDS],
        genres=m.genre_list,
        people=[(mp.nconst, mp.role, mp.ordering) for mp in m.people],
        year=m.year,
        language=m.original_language,
    )


_ROLE_RANK = {"director": 0, "writer": 1, "cast": 2}


def _best_roles(people: list[tuple[str, str, int]]) -> dict[str, str]:
    """nconst -> most notable role on this movie (director > writer > cast)."""
    best: dict[str, str] = {}
    for nconst, role, _ in people:
        if nconst not in best or _ROLE_RANK.get(role, 9) < _ROLE_RANK.get(best[nconst], 9):
            best[nconst] = role
    return best
