"""Scoring on top of the movie index. See README "How recommendations work"."""

from collections import Counter
from dataclasses import dataclass, field

import numpy as np

from app.recommender.index import NO_COLLECTION, MovieIndex

MAX_PICKS = 5

# Blender score = CENTROID_WEIGHT * sim(centroid) + (1 - CENTROID_WEIGHT) * min_i sim(pick_i)
CENTROID_WEIGHT = 0.7
# Final score = base * (QUALITY_FLOOR + (1 - QUALITY_FLOOR) * quality)
QUALITY_FLOOR = 0.85
# MMR trade-off between relevance and novelty when choosing the final k.
MMR_LAMBDA = 0.8
CANDIDATE_POOL = 50


class UnknownMoviesError(KeyError):
    def __init__(self, imdb_ids: list[str]) -> None:
        super().__init__(imdb_ids)
        self.imdb_ids = imdb_ids


@dataclass
class Reasons:
    keywords: list[str] = field(default_factory=list)
    genres: list[str] = field(default_factory=list)
    people: list[str] = field(default_factory=list)  # "Michael Mann (director)"


@dataclass
class Match:
    imdb_id: str
    score: float
    reasons: Reasons


def _quality_factor(index: MovieIndex) -> np.ndarray:
    return QUALITY_FLOOR + (1 - QUALITY_FLOOR) * index.quality


def _mmr(index: MovieIndex, scores: np.ndarray, k: int, lam: float = MMR_LAMBDA) -> list[int]:
    """Greedy maximal-marginal-relevance pick of k rows from the top of `scores`."""
    valid = np.flatnonzero(np.isfinite(scores))
    if len(valid) == 0:
        return []
    pool = valid[np.argsort(-scores[valid])[:CANDIDATE_POOL]]
    vecs = index.matrix[pool]
    chosen: list[int] = []
    max_sim = np.full(len(pool), -np.inf, dtype=np.float32)
    for _ in range(min(k, len(pool))):
        redundancy = np.where(np.isfinite(max_sim), max_sim, 0.0)
        mmr = lam * scores[pool] - (1 - lam) * redundancy
        mmr[chosen] = -np.inf
        best = int(np.argmax(mmr))
        chosen.append(best)
        max_sim = np.maximum(max_sim, vecs @ vecs[best])
    return [int(pool[i]) for i in chosen]


def explain(index: MovieIndex, row: int, source_rows: list[int]) -> Reasons:
    """What a result shares with the movies it was recommended from."""
    kw_counts: Counter[str] = Counter()
    genre_counts: Counter[str] = Counter()
    people_counts: Counter[str] = Counter()
    result_kw = index.keyword_sets[row]
    result_genres = set(index.features[row].genres)
    result_people = index.people_roles[row]
    for src in source_rows:
        kw_counts.update(result_kw & index.keyword_sets[src])
        genre_counts.update(result_genres & set(index.features[src].genres))
        people_counts.update(result_people.keys() & index.people_roles[src].keys())

    # Keywords: shared with the most sources first, then the rarest (most specific).
    keywords = sorted(kw_counts, key=lambda k: (-kw_counts[k], -index.keyword_idf.get(k, 0), k))
    genres = sorted(genre_counts, key=lambda g: (-genre_counts[g], g))
    people = sorted(people_counts, key=lambda p: (-people_counts[p], p))
    return Reasons(
        keywords=keywords[:3],
        genres=genres[:3],
        people=[f"{index.person_names.get(p, p)} ({result_people[p]})" for p in people[:2]],
    )


def blend(index: MovieIndex, imdb_ids: list[str], k: int = 3) -> list[Match]:
    """Top-k movies matching all of the given picks."""
    picks = list(dict.fromkeys(imdb_ids))  # dedupe, keep order
    if not 1 <= len(picks) <= MAX_PICKS:
        raise ValueError(f"pick between 1 and {MAX_PICKS} movies")
    unknown = [i for i in picks if i not in index.row]
    if unknown:
        raise UnknownMoviesError(unknown)

    rows = [index.row[i] for i in picks]
    pick_vecs = index.matrix[rows]
    per_pick = index.matrix @ pick_vecs.T  # N x picks
    centroid = pick_vecs.mean(axis=0)
    centroid /= np.linalg.norm(centroid) or 1.0
    base = CENTROID_WEIGHT * (index.matrix @ centroid) + (1 - CENTROID_WEIGHT) * per_pick.min(
        axis=1
    )
    scores = (base * _quality_factor(index)).astype(np.float32)

    # Exclude the picks themselves and anything in the same TMDB collection
    # (sequels, prequels, remakes in a franchise).
    scores[rows] = -np.inf
    pick_collections = {int(c) for c in index.collection[rows] if c != NO_COLLECTION}
    if pick_collections:
        scores[np.isin(index.collection, list(pick_collections))] = -np.inf

    # MMR decides *which* k; show them best-first.
    chosen = sorted(_mmr(index, scores, k), key=lambda r: -scores[r])
    return [
        Match(imdb_id=index.ids[r], score=float(scores[r]), reasons=explain(index, r, rows))
        for r in chosen
    ]
