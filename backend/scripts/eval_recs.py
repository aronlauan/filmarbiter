"""Recommendation quality check against the real catalog (dev tool, not a test).

    uv run python -m scripts.eval_recs [--weights overview=0.4,keywords=0.3,...]
                                       [--quality-floor 0.85] [--letterboxd USER] [-v]

For each check blend it reports how many hand-picked "expected" films land in the
top 10 (hits@10), and the top 3 the user would actually see with their IMDb
ratings. With --letterboxd it also scores that user's latest import: mean IMDb
rating of the picks and how varied the "because you rated" films are.

Block weights can be overridden without rebuilding vectors: each block of the
saved matrix is recovered by re-normalising its slice (blocks are unit length
before weighting), then re-weighted and re-normalised.
"""

import argparse
import json
from collections import Counter

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import engine
from app.models import LetterboxdFilm, Movie
from app.recommender import engine as rec
from app.recommender.index import MovieIndex

# (picks, expected) as "Title (Year)". Expectations are human judgement: films a
# person who loves the picks would plausibly want, not ground truth.
CHECKS: dict[str, tuple[list[str], list[str]]] = {
    "mann": (
        ["Heat (1995)", "Collateral (2004)"],
        [
            "Thief (1981)",
            "Miami Vice (2006)",
            "The Town (2010)",
            "Drive (2011)",
            "Sicario (2015)",
            "Den of Thieves (2018)",
            "Public Enemies (2009)",
            "Nightcrawler (2014)",
            "To Live and Die in L.A. (1985)",
            "The Insider (1999)",
        ],
    ),
    "neo-noir drive": (
        ["Heat (1995)", "Collateral (2004)", "Drive (2011)"],
        [
            "Thief (1981)",
            "The Driver (1978)",
            "Nightcrawler (2014)",
            "Baby Driver (2017)",
            "To Live and Die in L.A. (1985)",
            "Only God Forgives (2013)",
            "The Town (2010)",
            "Miami Vice (2006)",
            "Good Time (2017)",
        ],
    ),
    "pixar": (
        ["Toy Story (1995)", "WALL·E (2008)", "Up (2009)"],
        [
            "Inside Out (2015)",
            "Finding Nemo (2003)",
            "Monsters, Inc. (2001)",
            "Ratatouille (2007)",
            "Coco (2017)",
            "The Incredibles (2004)",
            "Soul (2020)",
            "Big Hero 6 (2014)",
            "Wreck-It Ralph (2012)",
        ],
    ),
    "a24 folk horror": (
        ["Hereditary (2018)", "Midsommar (2019)", "The Witch (2015)"],
        [
            "The Lighthouse (2019)",
            "Saint Maud (2019)",
            "Men (2022)",
            "The Babadook (2014)",
            "It Follows (2014)",
            "Lamb (2021)",
            "The Wicker Man (1973)",
            "Talk to Me (2022)",
            "X (2022)",
            "Pearl (2022)",
        ],
    ),
    "kurosawa": (
        ["Seven Samurai (1954)", "Kagemusha: The Shadow Warrior (1980)"],
        [
            "Ran (1985)",
            "Yojimbo (1961)",
            "Sanjuro (1962)",
            "Throne of Blood (1957)",
            "The Hidden Fortress (1958)",
            "Harakiri (1962)",
            "13 Assassins (2010)",
            "Rashomon (1950)",
        ],
    ),
    "ghibli + bong": (
        ["Spirited Away (2001)", "Parasite (2019)"],
        [
            "Okja (2017)",
            "Shoplifters (2018)",
            "Burning (2018)",
            "Howl's Moving Castle (2004)",
            "The Host (2006)",
            "Memories of Murder (2003)",
            "Princess Mononoke (1997)",
            "My Neighbor Totoro (1988)",
        ],
    ),
    "romance walk-and-talk": (
        ["Before Sunrise (1995)", "Lost in Translation (2003)"],
        [
            "Before Sunset (2004)",
            "In the Mood for Love (2000)",
            "Her (2013)",
            "Past Lives (2023)",
            "Once (2007)",
            "Chungking Express (1994)",
            "Columbus (2017)",
            "Paterson (2016)",
            "Eternal Sunshine of the Spotless Mind (2004)",
        ],
    ),
    "action": (
        ["Mad Max: Fury Road (2015)", "John Wick (2014)"],
        [
            "Dredd (2012)",
            "The Raid (2011)",
            "Atomic Blonde (2017)",
            "Nobody (2021)",
            "Upgrade (2018)",
            "Extraction (2020)",
            "The Raid 2 (2014)",
            "Edge of Tomorrow (2014)",
        ],
    ),
}


def resolve(session: Session, label: str) -> str | None:
    title, _, year = label.rpartition(" (")
    rows = (
        session.execute(
            select(Movie.imdb_id)
            .where(Movie.title == title, Movie.year == int(year.rstrip(")")))
            .order_by(Movie.imdb_votes.desc())
        )
        .scalars()
        .all()
    )
    return rows[0] if rows else None


def reweight(index: MovieIndex, weights: dict[str, float]) -> None:
    meta = json.loads((settings.data_dir / "vectors.json").read_text())
    full = dict(meta["weights"], **weights)
    parts = []
    for name, (start, stop) in meta["blocks"].items():
        block = index.matrix[:, start:stop]
        norms = np.linalg.norm(block, axis=1, keepdims=True)
        unit = np.divide(block, norms, out=np.zeros_like(block), where=norms > 0)
        parts.append(unit * np.sqrt(full[name]))
    m = np.hstack(parts)
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    index.matrix = np.divide(m, norms, out=np.zeros_like(m), where=norms > 0).astype(np.float32)
    print("weights:", {k: round(v, 3) for k, v in full.items()})


def blend_scores(index: MovieIndex, rows: list[int]) -> np.ndarray:
    """Same scoring as engine.blend, before MMR, for ranking the whole catalog."""
    pick_vecs = index.matrix[rows]
    centroid = pick_vecs.mean(axis=0)
    centroid /= np.linalg.norm(centroid) or 1.0
    base = rec.CENTROID_WEIGHT * (index.matrix @ centroid) + (1 - rec.CENTROID_WEIGHT) * (
        index.matrix @ pick_vecs.T
    ).min(axis=1)
    scores = base * rec._quality_factor(index)
    scores[rows] = -np.inf
    colls = {int(c) for c in index.collection[rows] if c != -1}
    if colls:
        scores[np.isin(index.collection, list(colls))] = -np.inf
    return scores


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", default="", help="e.g. people=0.2,overview=0.3")
    ap.add_argument("--quality-floor", type=float)
    ap.add_argument("--centroid-weight", type=float)
    ap.add_argument("--letterboxd", default=None, help="username with a finished import")
    ap.add_argument("-v", "--verbose", action="store_true", help="also print the top 10")
    args = ap.parse_args()

    index = MovieIndex.load(engine, settings.data_dir / "vectors.npz")
    if args.weights:
        reweight(index, {k: float(v) for k, v in (p.split("=") for p in args.weights.split(","))})
    if args.quality_floor is not None:
        rec.QUALITY_FLOOR = args.quality_floor
    if args.centroid_weight is not None:
        rec.CENTROID_WEIGHT = args.centroid_weight
    print(f"quality_floor={rec.QUALITY_FLOOR} centroid_weight={rec.CENTROID_WEIGHT}\n")

    with Session(engine) as s:
        movies = {m.imdb_id: m for m in s.scalars(select(Movie))}
        label = lambda i: f"{movies[i].title} ({movies[i].year}, {movies[i].imdb_rating})"  # noqa: E731

        total_hits = total_expected = 0
        top3_ratings: list[float] = []
        for name, (pick_labels, expected_labels) in CHECKS.items():
            picks = [resolve(s, p) for p in pick_labels]
            if None in picks:
                print(f"[{name}] skipped: missing pick {pick_labels}")
                continue
            expected = {e: resolve(s, e) for e in expected_labels}
            exp_ids = {i for i in expected.values() if i in index.row}
            rows = [index.row[p] for p in picks]  # type: ignore[index]
            scores = blend_scores(index, rows)
            top10 = [index.ids[r] for r in np.argsort(-scores)[:10]]
            hits = [i for i in top10 if i in exp_ids]
            total_hits += len(hits)
            total_expected += min(len(exp_ids), 10)
            shown = rec.blend(index, picks)  # type: ignore[arg-type]
            top3_ratings += [movies[m.imdb_id].imdb_rating or 0 for m in shown]
            print(
                f"[{name}] hits@10 {len(hits)}/{len(exp_ids)}  top3: "
                + " | ".join(label(m.imdb_id) for m in shown)
            )
            if args.verbose:
                marked = [label(i) + ("*" if i in exp_ids else "") for i in top10]
                print("    top10:", ", ".join(marked))
        print(
            f"\nTOTAL hits@10 {total_hits}/{total_expected}   "
            f"mean IMDb of shown top3 {np.mean(top3_ratings):.2f}"
        )

        if args.letterboxd:
            films = s.scalars(
                select(LetterboxdFilm).where(
                    LetterboxdFilm.username == args.letterboxd, LetterboxdFilm.imdb_id.is_not(None)
                )
            ).all()
            recs = rec.recommend_for_profile(
                index,
                [rec.RatedFilm(f.imdb_id, f.rating, f.liked) for f in films],
                k=10,  # type: ignore[arg-type]
            )
            because = Counter(b for r in recs for b in r.because)
            ratings = [movies[r.imdb_id].imdb_rating or 0 for r in recs]
            kw = np.mean([len(r.reasons.keywords) for r in recs])
            print(
                f"\n[letterboxd {args.letterboxd}] mean IMDb {np.mean(ratings):.2f}  "
                f"distinct because {len(because)}/{sum(because.values())}  "
                f"most repeated: {[(movies[i].title, n) for i, n in because.most_common(3)]}  "
                f"avg why-keywords {kw:.1f}"
            )
            for r in recs:
                because_titles = [movies[b].title for b in r.because]
                print(f"    {label(r.imdb_id)}  because {because_titles}  why {r.reasons.keywords}")


if __name__ == "__main__":
    main()
