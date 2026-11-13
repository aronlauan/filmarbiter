"""Lay out the movie vectors in 2D for the Blender's movie theater.

    uv run python -m ingest.build_map

Reads data/vectors.npz (run `make vectors` first) and writes data/map.npz
(ids + xy, plus the theater's sections for the current MAP_CANDIDATES most-voted
films, so the API doesn't need scikit-learn) and data/map.json (build metadata).
Restart the API afterwards.
"""

import json
import logging
import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.config import settings
from app.recommender.movie_map import layout, map_candidates, split_sections

log = logging.getLogger("ingest.build_map")


def build(
    vectors_path: Path,
    out_path: Path,
    seed: int = 0,
    eng: Engine | None = None,
    candidates: int | None = None,
) -> dict:
    """With `eng` and `candidates`, also precompute the theater's sections."""
    t0 = time.perf_counter()
    with np.load(vectors_path, allow_pickle=False) as npz:
        ids = npz["ids"]
        matrix = npz["matrix"]
    log.info("laying out %d movies (%d dims); takes a minute or two", len(ids), matrix.shape[1])
    xy = layout(matrix, seed=seed)
    sections: dict[str, np.ndarray] = {}
    if eng is not None and candidates is not None:
        str_ids = [str(x) for x in ids]
        rows = {imdb_id: i for i, imdb_id in enumerate(str_ids)}
        with Session(eng) as s:
            cand = [m.imdb_id for m in map_candidates(s, str_ids, candidates)]
        true_xy = xy.astype(np.float32)[[rows[i] for i in cand]].reshape(-1, 2)
        sections = {
            "section_ids": np.array(cand, dtype=ids.dtype),
            "section_labels": split_sections(true_xy),
        }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(out_path, ids=ids, xy=xy, **sections)
    meta = {
        "built_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "movies": len(ids),
        "seed": seed,
        "seconds": round(time.perf_counter() - t0, 1),
    }
    out_path.with_suffix(".json").write_text(json.dumps(meta, indent=2))
    log.info("wrote %s: %s", out_path, meta)
    return meta


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    from app.db import engine

    build(
        settings.data_dir / "vectors.npz",
        settings.data_dir / "map.npz",
        eng=engine,
        candidates=settings.map_candidates,
    )


if __name__ == "__main__":
    main()
