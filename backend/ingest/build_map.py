"""Lay out the movie vectors in 2D for the Blender's movie theater.

    uv run python -m ingest.build_map

Reads data/vectors.npz (run `make vectors` first) and writes data/map.npz
(ids + xy) and data/map.json (build metadata). Restart the API afterwards.
"""

import json
import logging
import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from app.config import settings
from app.recommender.movie_map import layout

log = logging.getLogger("ingest.build_map")


def build(vectors_path: Path, out_path: Path, seed: int = 0) -> dict:
    t0 = time.perf_counter()
    with np.load(vectors_path, allow_pickle=False) as npz:
        ids = npz["ids"]
        matrix = npz["matrix"]
    log.info("laying out %d movies (%d dims); takes a minute or two", len(ids), matrix.shape[1])
    xy = layout(matrix, seed=seed)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(out_path, ids=ids, xy=xy)
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
    build(settings.data_dir / "vectors.npz", settings.data_dir / "map.npz")


if __name__ == "__main__":
    main()
