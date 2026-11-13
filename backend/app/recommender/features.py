"""Turn movie metadata into one combined, L2-normalised vector per movie.

The combined vector is the concatenation of per-block vectors, each scaled to
unit length and then by sqrt(weight). For two movies with every block present,
their dot product is therefore sum(weight_b * cosine_b): each weight is that
block's literal share of the similarity score. A final row normalisation lets
movies missing a block (e.g. no TMDB keywords) share the score among the blocks
they do have. See the README "How recommendations work" section.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np

# scipy and scikit-learn are only needed to build vectors (ingest), not to serve them,
# so they're imported inside the build functions: the API stays ~75 MB lighter.
if TYPE_CHECKING:
    from scipy import sparse

Embedder = Callable[[list[str]], np.ndarray]

# How much a credit counts toward the "people" block, by role / billing.
ROLE_WEIGHTS = {"director": 1.0, "writer": 0.7}
CAST_WEIGHTS = [1.0, 0.9, 0.8, 0.7, 0.6]

# TMDB tags about the release or production rather than the film itself. They'd make
# e.g. every sequel similar to every other sequel, so they're ignored for matching
# and explanations. Tags about the viewing experience ("black and white", "anime",
# "based on true story") are kept.
IGNORED_KEYWORDS = frozenset(
    {
        "aftercreditsstinger",
        "duringcreditsstinger",
        "beforecreditsstinger",
        "post-credits scene",
        "credits cookie",
        "bloopers in credits",
        "animated credits",
        "sequel",
        "prequel",
        "remake",
        "live action remake",
        "woman director",
        "3d",
        "short film",
    }
)

ERA_CENTERS = np.arange(1900, 2036, 5, dtype=np.float32)
ERA_SIGMA = 8.0  # similarity ~0.68 at a 10-year gap, ~0.21 at 20


@dataclass
class MovieFeatures:
    imdb_id: str
    overview: str | None = None
    keywords: list[str] = field(default_factory=list)
    genres: list[str] = field(default_factory=list)
    people: list[tuple[str, str, int]] = field(default_factory=list)  # (nconst, role, ordering)
    year: int | None = None
    language: str | None = None


@dataclass(frozen=True)
class BlockWeights:
    overview: float = 0.405
    keywords: float = 0.27
    genres: float = 0.135
    people: float = 0.09
    era: float = 0.05
    language: float = 0.05

    def as_dict(self) -> dict[str, float]:
        return dict(self.__dict__)


def _l2_rows(m: np.ndarray) -> np.ndarray:
    """Row-normalise; all-zero rows (missing data) stay zero."""
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    return np.divide(m, norms, out=np.zeros_like(m), where=norms > 0)


def _reduce(x: sparse.csr_matrix, dims: int, seed: int = 0) -> np.ndarray:
    """TF-IDF matrix -> dense, at most `dims` columns via truncated SVD."""
    if x.shape[1] <= dims or min(x.shape) <= 2:
        return x.toarray().astype(np.float32)
    from sklearn.decomposition import TruncatedSVD

    n = min(dims, x.shape[0] - 1, x.shape[1] - 1)
    return TruncatedSVD(n_components=n, random_state=seed).fit_transform(x).astype(np.float32)


def _tfidf_lists(docs: Sequence[list[str]], min_df: int) -> sparse.csr_matrix:
    """TF-IDF over pre-tokenised lists (each list is a set of tags)."""
    from scipy import sparse
    from sklearn.feature_extraction.text import TfidfVectorizer

    if not any(docs):
        return sparse.csr_matrix((len(docs), 0), dtype=np.float32)
    vec = TfidfVectorizer(
        analyzer=lambda d: d,  # already tokenised
        lowercase=False,
        binary=True,
        min_df=min(min_df, len(docs)),
        dtype=np.float32,
    )
    try:
        return vec.fit_transform(docs).tocsr()
    except ValueError:  # every term pruned by min_df
        return sparse.csr_matrix((len(docs), 0), dtype=np.float32)


def overview_block(movies: Sequence[MovieFeatures], embed: Embedder) -> np.ndarray:
    idx = [i for i, m in enumerate(movies) if m.overview]
    if not idx:
        return np.zeros((len(movies), 1), dtype=np.float32)
    emb = np.asarray(embed([movies[i].overview or "" for i in idx]), dtype=np.float32)
    out = np.zeros((len(movies), emb.shape[1]), dtype=np.float32)
    out[idx] = emb
    return out


def keyword_block(movies: Sequence[MovieFeatures], dims: int = 128) -> np.ndarray:
    # min_df=2: a tag on a single movie can't make two movies similar.
    return _reduce(_tfidf_lists([m.keywords for m in movies], min_df=2), dims)


def genre_block(movies: Sequence[MovieFeatures]) -> np.ndarray:
    # IDF down-weights ubiquitous genres (Drama) relative to rare ones (Western).
    return _tfidf_lists([m.genres for m in movies], min_df=1).toarray()


def people_block(movies: Sequence[MovieFeatures], dims: int = 128) -> np.ndarray:
    from scipy import sparse
    from sklearn.feature_extraction.text import TfidfTransformer

    vocab: dict[str, int] = {}
    rows, cols, vals = [], [], []
    for i, m in enumerate(movies):
        weights: dict[str, float] = {}
        for nconst, role, ordering in m.people:
            if role == "cast":
                w = CAST_WEIGHTS[ordering] if ordering < len(CAST_WEIGHTS) else CAST_WEIGHTS[-1]
            else:
                w = ROLE_WEIGHTS.get(role, 0.5)
            weights[nconst] = max(weights.get(nconst, 0.0), w)  # director-writer counts once
        for nconst, w in weights.items():
            rows.append(i)
            cols.append(vocab.setdefault(nconst, len(vocab)))
            vals.append(w)
    counts = sparse.csr_matrix((vals, (rows, cols)), shape=(len(movies), len(vocab)))
    # Drop people credited on only one movie: they can't link two films.
    df = np.asarray((counts > 0).sum(axis=0)).ravel()
    counts = counts[:, df >= 2] if len(movies) > 2 else counts
    if counts.shape[1] == 0:
        return np.zeros((len(movies), 1), dtype=np.float32)
    tfidf = TfidfTransformer().fit_transform(counts).tocsr()
    return _reduce(tfidf, dims)


def era_block(movies: Sequence[MovieFeatures]) -> np.ndarray:
    years = np.array([m.year if m.year else np.nan for m in movies], dtype=np.float32)
    out = np.exp(-((years[:, None] - ERA_CENTERS[None, :]) ** 2) / (2 * ERA_SIGMA**2))
    return np.nan_to_num(out, nan=0.0).astype(np.float32)


def language_block(movies: Sequence[MovieFeatures]) -> np.ndarray:
    langs = sorted({m.language for m in movies if m.language})
    col = {lang: j for j, lang in enumerate(langs)}
    out = np.zeros((len(movies), max(len(langs), 1)), dtype=np.float32)
    for i, m in enumerate(movies):
        if m.language:
            out[i, col[m.language]] = 1.0
    return out


def build_matrix(
    movies: Sequence[MovieFeatures],
    embed: Embedder,
    weights: BlockWeights = BlockWeights(),  # noqa: B008
    svd_dims: int = 128,
) -> tuple[np.ndarray, dict[str, slice]]:
    """Return (N x D float32 matrix with unit-length rows, {block: column slice})."""
    blocks = {
        "overview": overview_block(movies, embed),
        "keywords": keyword_block(movies, svd_dims),
        "genres": genre_block(movies),
        "people": people_block(movies, svd_dims),
        "era": era_block(movies),
        "language": language_block(movies),
    }
    w = weights.as_dict()
    parts, slices, start = [], {}, 0
    for name, block in blocks.items():
        block = _l2_rows(block.astype(np.float32)) * np.float32(np.sqrt(w[name]))
        parts.append(block)
        slices[name] = slice(start, start + block.shape[1])
        start += block.shape[1]
    return _l2_rows(np.hstack(parts)), slices
