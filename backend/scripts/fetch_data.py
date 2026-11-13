"""Download the built data files (vectors + map) at deploy time.

    DATA_RELEASE_URL=https://github.com/OWNER/REPO/releases/download/TAG \\
        uv run python -m scripts.fetch_data

The files are too big for git, so `make data-bundle` writes them plus a SHA256SUMS
file to data/release/; upload those as assets of a GitHub release and point
DATA_RELEASE_URL at it. Every file is checked against SHA256SUMS, so a partial or
mismatched upload fails the build instead of booting with bad vectors.

They must be built from the same catalog that's in the production database: after
re-ingesting, rebuild vectors + map, copy the database, publish a new release, and
bump DATA_RELEASE_URL.
"""

import hashlib
import logging
import os
import sys

import httpx

from app.config import settings

log = logging.getLogger("scripts.fetch_data")

FILES = ("vectors.npz", "vectors.json", "map.npz", "map.json")


def parse_sums(text: str) -> dict[str, str]:
    """`sha256sum`/`shasum -a 256` output -> {filename: hex digest}."""
    sums = {}
    for line in text.splitlines():
        if line.strip():
            digest, name = line.split(maxsplit=1)
            sums[name.lstrip("*")] = digest.lower()
    return sums


def fetch(base_url: str) -> None:
    base_url = base_url.rstrip("/")
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    with httpx.Client(follow_redirects=True, timeout=120) as client:
        resp = client.get(f"{base_url}/SHA256SUMS")
        resp.raise_for_status()
        sums = parse_sums(resp.text)
        for name in FILES:
            if name not in sums:
                raise SystemExit(f"SHA256SUMS has no entry for {name}")
            dest = settings.data_dir / name
            tmp = dest.with_name(dest.name + ".part")
            h = hashlib.sha256()
            with client.stream("GET", f"{base_url}/{name}") as r, tmp.open("wb") as f:
                r.raise_for_status()
                for chunk in r.iter_bytes(1 << 20):
                    h.update(chunk)
                    f.write(chunk)
            if h.hexdigest() != sums[name]:
                tmp.unlink()
                raise SystemExit(f"{name}: checksum mismatch (expected {sums[name]})")
            tmp.replace(dest)
            log.info("%s: %.1f MB, checksum ok", name, dest.stat().st_size / 1e6)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    base_url = os.environ.get("DATA_RELEASE_URL")
    if not base_url:
        sys.exit("set DATA_RELEASE_URL to the GitHub release download URL")
    fetch(base_url)


if __name__ == "__main__":
    main()
