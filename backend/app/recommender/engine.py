"""Scoring on top of the movie index. See README "How recommendations work"."""

from collections import Counter
from dataclasses import dataclass, field

import numpy as np

from app.recommender.index import NO_COLLECTION, MovieIndex
from app.recommender.sensitive import is_sensitive

MAX_PICKS = 5

# Blender score = CENTROID_WEIGHT * sim(centroid) + (1 - CENTROID_WEIGHT) * min_i sim(pick_i)
CENTROID_WEIGHT = 0.7
# Final score = base * (floor + (1 - floor) * quality), quality in 0..1 (IMDb-based).
# Tuned with scripts/eval_recs.py: 0.85 let 4-5 star IMDb films into the top 3; lower
# floors improved expected-film hits until results drifted toward famous films
# regardless of the picks (Pulp Fiction for any crime blend) at ~0.4. A Letterboxd
# profile averages hundreds of films into a blander vector and benefits from more.
QUALITY_FLOOR = 0.5
PROFILE_QUALITY_FLOOR = 0.4
# MMR trade-off between relevance and novelty when choosing the final k.
MMR_LAMBDA = 0.8
CANDIDATE_POOL = 50
# Match percentage shown on Blender results: sqrt((score - floor) / (ceil - floor)),
# clamped to 0..100. Calibrated on 400 random blends: top results score ~0.33 (p10),
# ~0.37 (median), ~0.62 (p99); coherent blends land at ~0.45-0.55. So a scattered
# blend's top pick reads ~65%, a good one ~80-90%, and only rare near-perfect fits hit
# 100. The square root spreads out the top of the range, where most results sit.
MATCH_FLOOR = 0.15
MATCH_CEIL = 0.65


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


def match_percent(score: float) -> int:
    """A blend score as a 0-100 match percentage (see MATCH_FLOOR / MATCH_CEIL).
    Monotonic in the score, so results ranked by score never show a lower rank
    with a higher percentage."""
    t = (score - MATCH_FLOOR) / (MATCH_CEIL - MATCH_FLOOR)
    return round(100 * min(1.0, max(0.0, t)) ** 0.5)


def _quality_factor(index: MovieIndex, floor: float | None = None) -> np.ndarray:
    floor = QUALITY_FLOOR if floor is None else floor
    return floor + (1 - floor) * index.quality


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


def explain(
    index: MovieIndex, row: int, source_rows: list[int], by_rarity: bool = False
) -> Reasons:
    """What a result shares with the movies it was recommended from.

    Keywords about race, ethnicity or gender are never given as a reason (see
    sensitive.py). Keywords are ranked by how many sources share them, then by rarity. With many
    sources (a Letterboxd profile) pass by_rarity=True to rank by count x IDF
    instead, so ubiquitous tags ("based on novel or book") don't win on count alone.
    """
    kw_counts: Counter[str] = Counter()
    genre_counts: Counter[str] = Counter()
    people_counts: Counter[str] = Counter()
    result_kw = index.keyword_sets[row]
    result_genres = set(index.features[row].genres)
    result_people = index.people_roles[row]
    for src in source_rows:
        kw_counts.update(k for k in result_kw & index.keyword_sets[src] if not is_sensitive(k))
        genre_counts.update(result_genres & set(index.features[src].genres))
        people_counts.update(result_people.keys() & index.people_roles[src].keys())

    idf = index.keyword_idf
    if by_rarity:
        keywords = sorted(kw_counts, key=lambda k: (-kw_counts[k] * idf.get(k, 0), k))
    else:
        keywords = sorted(kw_counts, key=lambda k: (-kw_counts[k], -idf.get(k, 0), k))
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


# --- Letterboxd profile -----------------------------------------------------

# A like counts as this many stars above the user's own average.
LIKE_BONUS = 0.5
# Films rated below the user's average push the profile away at reduced strength,
# so it doesn't swing toward "anything unlike what I disliked".
NEGATIVE_SCALE = 0.5
# Each time one of the user's films is cited in "because you rated", its chance of
# being cited again shrinks by this factor, so picks draw on more of their history.
BECAUSE_REPEAT_PENALTY = 0.6
# How many of the user's related, positively rated films a "Why" line draws on.
EXPLAIN_SOURCES = 25


@dataclass
class RatedFilm:
    imdb_id: str
    rating: float | None  # 0.5..5 stars; None = logged without a rating
    liked: bool = False


@dataclass
class ProfileMatch(Match):
    because: list[str] = field(default_factory=list)  # IMDb IDs of the user's films


def profile_weights(films: list[RatedFilm]) -> np.ndarray:
    """Per-film weight: (rating - user's mean) + like bonus; negatives scaled down.
    Falls back to equal positive weights when that leaves nothing positive
    (e.g. every film rated the same, or no ratings at all)."""
    rated = [f.rating for f in films if f.rating is not None]
    mean = float(np.mean(rated)) if rated else 0.0
    w = np.array(
        [
            ((f.rating - mean) if f.rating is not None else 0.0) + (LIKE_BONUS if f.liked else 0.0)
            for f in films
        ],
        dtype=np.float32,
    )
    w = np.where(w < 0, w * NEGATIVE_SCALE, w)
    if not (w > 0).any():
        # No signal beyond "they watched these": treat rated-at-or-above-mean (or,
        # with no ratings, everything logged) as equally liked.
        w = np.array(
            [1.0 if (f.rating is None or f.rating >= mean or f.liked) else 0.0 for f in films],
            dtype=np.float32,
        )
    return w


def recommend_for_profile(
    index: MovieIndex, films: list[RatedFilm], k: int = 10
) -> list[ProfileMatch]:
    """Top-k unseen movies for a user's logged films."""
    known = [f for f in films if f.imdb_id in index.row]
    if not known:
        return []
    rows = [index.row[f.imdb_id] for f in known]
    weights = profile_weights(known)
    if not weights.any():
        return []

    profile = weights @ index.matrix[rows]
    profile /= np.linalg.norm(profile) or 1.0
    quality = _quality_factor(index, PROFILE_QUALITY_FLOOR)
    scores = ((index.matrix @ profile) * quality).astype(np.float32)
    scores[rows] = -np.inf  # never recommend something they've logged

    chosen = sorted(_mmr(index, scores, k), key=lambda r: -scores[r])
    pos = np.array([r for r, w in zip(rows, weights, strict=True) if w > 0])

    cited: Counter[int] = Counter()
    results = []
    for r in chosen:
        sims = index.matrix[pos] @ index.matrix[r]
        # "Because you rated": the user's liked films most like this pick, avoiding
        # citing the same favorites on every result.
        penalty = np.array([BECAUSE_REPEAT_PENALTY ** cited[int(p)] for p in pos])
        top = [int(pos[i]) for i in np.argsort(-(sims * penalty))[:3]]
        cited.update(top)
        related = [int(pos[i]) for i in np.argsort(-sims)[:EXPLAIN_SOURCES]]
        results.append(
            ProfileMatch(
                imdb_id=index.ids[r],
                score=float(scores[r]),
                reasons=explain(index, r, related, by_rarity=True),
                because=[index.ids[t] for t in top],
            )
        )
    return results
