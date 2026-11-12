"""Build the movie vector matrix used by the recommender.

    uv run python -m ingest.build_vectors

Writes data/vectors.npz (ids + matrix) and data/vectors.json (build metadata).
Re-run after any IMDb/TMDB ingest; the API loads the file at startup.
"""

import json
import logging
import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, selectinload

from app.config import settings
from app.db import engine as default_engine
from app.models import Movie
from app.recommender.features import BlockWeights, Embedder, build_matrix
from app.recommender.index import movie_features

log = logging.getLogger("ingest.build_vectors")

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"


def sentence_embedder(model_name: str = MODEL_NAME) -> Embedder:
    from sentence_transformers import SentenceTransformer  # heavy import; keep lazy

    model = SentenceTransformer(model_name)

    def embed(texts: list[str]) -> np.ndarray:
        return model.encode(texts, batch_size=64, normalize_embeddings=True, show_progress_bar=True)

    return embed


def weights_from_settings() -> BlockWeights:
    return BlockWeights(
        overview=settings.weight_overview,
        keywords=settings.weight_keywords,
        genres=settings.weight_genres,
        people=settings.weight_people,
        era=settings.weight_era,
        language=settings.weight_language,
    )


def build(eng: Engine, out_path: Path, embed: Embedder, weights: BlockWeights) -> dict:
    t0 = time.perf_counter()
    with Session(eng) as s:
        movies = s.scalars(
            select(Movie)
            .options(selectinload(Movie.keywords), selectinload(Movie.people))
            .order_by(Movie.imdb_id)
        ).all()
        features = [movie_features(m) for m in movies]
    log.info("loaded %d movies", len(features))

    matrix, slices = build_matrix(features, embed, weights)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(out_path, ids=np.array([f.imdb_id for f in features]), matrix=matrix)
    meta = {
        "built_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "movies": len(features),
        "dims": int(matrix.shape[1]),
        "blocks": {k: [v.start, v.stop] for k, v in slices.items()},
        "weights": weights.as_dict(),
        "model": MODEL_NAME,
        "seconds": round(time.perf_counter() - t0, 1),
    }
    out_path.with_suffix(".json").write_text(json.dumps(meta, indent=2))
    log.info("wrote %s: %s", out_path, meta)
    return meta


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    weights = weights_from_settings()
    total = sum(weights.as_dict().values())
    if abs(total - 1.0) > 1e-6:
        log.warning("block weights sum to %.3f, not 1.0", total)
    build(default_engine, settings.data_dir / "vectors.npz", sentence_embedder(), weights)


if __name__ == "__main__":
    main()
