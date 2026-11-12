"""In-memory movie index: the vector matrix plus the per-movie metadata the
engine needs for scoring (quality, collection) and explanations (keywords,
genres, people)."""

import json
import logging
import math
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, selectinload

from app.models import Movie, MoviePerson
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
            matrix=matrix.astype(np.float32),
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

        with Session(eng) as s:
            movies = s.scalars(
                select(Movie).options(
                    selectinload(Movie.keywords),
                    selectinload(Movie.people).selectinload(MoviePerson.person),
                )
            ).all()
        movies = [m for m in movies if m.imdb_id in rows]
        if len(movies) < len(ids):
            log.warning("%d vectors have no catalog movie (stale)", len(ids) - len(movies))

        features = [movie_features(m) for m in movies]
        names = {mp.nconst: mp.person.name for m in movies for mp in m.people}
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
