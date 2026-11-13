"""2D map of the catalog, drawn as the Blender's movie theater.

Positions come from the recommender vectors (PCA -> t-SNE), so movies that the
recommender thinks are similar sit near each other. ingest/build_map.py computes
positions for every movie. At load, the most-voted movies are grouped into
sections (areas of the map, named after their most distinctive genre) and placed
on a seat grid: a free cell between seats, and a wider aisle between sections.
Crowded spots keep only their best-known films. Each seat is linked to its nearest
neighbors among the seats in vector space. Any other movie (a pick or blend result
without a seat) gets a seat on demand, next to where it belongs, so picks and
results always show up as seats like any other.
"""

import logging
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.models import Movie
from app.recommender.index import MovieIndex
from app.schemas import poster_url

log = logging.getLogger(__name__)

NEIGHBORS = 2  # links drawn from each pad
# Links longer than this on the map (in [-1, 1] units) are dropped: t-SNE keeps local
# neighborhoods but can place a few true neighbors far apart, and those long lines
# turn the board into a hairball.
MAX_LINK_LENGTH = 0.2
GRID = 0.025  # board grid spacing, in map units
PLACE_REACH = 3  # grid cells a seat may move from its true position to find room
SECTIONS = 10  # areas of the house, each named after a genre
# No seat of another section within this many cells (Chebyshev), which leaves an
# aisle at least AISLE empty cells wide between sections. Narrow on purpose: more
# films get seats, at the cost of less obvious aisles.
AISLE = 2
# Seats for movies outside the house's seating may move this far to find room.
EXTRA_REACH = 12
MIN_GENRE_SHARE = 0.3  # a section's name must fit at least this share of its films
# A section whose name fits fewer of its films than this gets a second genre
# ("COMEDY & DRAMA"), if adding one covers at least COMPOUND_GAIN more of them.
COMPOUND_BELOW = 0.8
COMPOUND_GAIN = 0.15

# IMDb genre -> section name.
SECTION_NAMES = {
    "Action": "ACTION",
    "Adventure": "ADVENTURE",
    "Animation": "ANIMATION",
    "Biography": "BIOPICS",
    "Comedy": "COMEDY",
    "Crime": "CRIME",
    "Documentary": "DOCS",
    "Drama": "DRAMA",
    "Family": "FAMILY",
    "Fantasy": "FANTASY",
    "Film-Noir": "NOIR",
    "History": "HISTORY",
    "Horror": "HORROR",
    "Music": "MUSIC",
    "Musical": "MUSICALS",
    "Mystery": "MYSTERY",
    "Romance": "ROMANCE",
    "Sci-Fi": "SCI-FI",
    "Sport": "SPORTS",
    "Thriller": "THRILLERS",
    "War": "WAR",
    "Western": "WESTERNS",
}


Cell = tuple[int, int]


def find_cell(
    x: float,
    y: float,
    section: int,
    taken: dict[Cell, int],
    grid: float = GRID,
    reach: int = PLACE_REACH,
    aisle: int = AISLE,
) -> Cell | None:
    """The free cell nearest (x, y) within `reach` rings: no other seat in the 8 cells
    around it and no seat of another section within `aisle` cells. None if there's
    no room. `taken` maps occupied cells to their section."""
    fx, fy = float(x) / grid, float(y) / grid
    gx, gy = round(fx), round(fy)
    near = range(-aisle, aisle + 1)

    def free(c: Cell) -> bool:
        for a in near:
            for b in near:
                other = taken.get((c[0] + a, c[1] + b))
                if other is not None and (max(abs(a), abs(b)) <= 1 or other != section):
                    return False
        return True

    for r in range(reach + 1):
        ring = [
            (gx + dx, gy + dy)
            for dx in range(-r, r + 1)
            for dy in range(-r, r + 1)
            if max(abs(dx), abs(dy)) == r
        ]
        room = [c for c in ring if free(c)]
        if room:
            return min(room, key=lambda c: (c[0] - fx) ** 2 + (c[1] - fy) ** 2)
    return None


def place_on_grid(
    xy: np.ndarray,
    sections: np.ndarray | None = None,
    grid: float = GRID,
    reach: int = PLACE_REACH,
    aisle: int = AISLE,
) -> list[Cell | None]:
    """Seat points in priority order, each in the free cell nearest its true position
    (see find_cell); None when there's no room (crowded area, lower priority)."""
    if sections is None:
        sections = np.zeros(len(xy), dtype=np.int64)
    taken: dict[Cell, int] = {}
    out: list[Cell | None] = []
    for (x, y), section in zip(xy, sections, strict=True):
        cell = find_cell(float(x), float(y), int(section), taken, grid, reach, aisle)
        if cell is not None:
            taken[cell] = int(section)
        out.append(cell)
    return out


def map_candidates(session: Session, ids: list[str], candidates: int) -> list[Movie]:
    """The most-voted mapped movies, which compete for seats in the theater."""
    return list(
        session.scalars(
            select(Movie)
            .where(Movie.imdb_id.in_(ids))
            .order_by(Movie.imdb_votes.desc(), Movie.imdb_id)
            .limit(candidates)
        ).all()
    )


def split_sections(xy: np.ndarray, k: int = SECTIONS) -> np.ndarray:
    """Section index per point: k-means on map positions, so sections are contiguous.
    Run by ingest/build_map.py and saved in map.npz; importing scikit-learn costs the
    API ~100 MB, so MovieMap.load only calls this when the saved sections are stale."""
    from sklearn.cluster import KMeans

    k = min(k, len(xy) // 10)
    if k < 2:
        return np.zeros(len(xy), dtype=np.int64)
    return KMeans(n_clusters=k, random_state=0, n_init=10).fit_predict(xy).astype(np.int64)


def name_sections(labels: np.ndarray, genres: list[list[str]]) -> dict[int, str]:
    """Name each section after the genre most over-represented in it (share in the
    section / share across all seats), among genres covering at least
    MIN_GENRE_SHARE of its films. Names don't repeat: when two sections want the same
    one, the stronger match keeps it and the other takes its next choice. A section
    left without a name falls back to its most common genre. Mixed sections, where
    that genre fits fewer than COMPOUND_BELOW of the films, get a second one: the
    genre that covers most of the rest (so a section of comedies and dramas reads
    "COMEDY & DRAMA", not just "COMEDY")."""
    n = len(labels)
    overall = Counter(g for gs in genres for g in gs)
    counts: dict[int, Counter[str]] = {}
    choices: dict[int, list[tuple[float, str]]] = {}
    for c in sorted(set(labels.tolist())):
        members = np.flatnonzero(labels == c)
        counts[c] = Counter(g for i in members for g in genres[i] if g in SECTION_NAMES)
        size = len(members)
        choices[c] = sorted(
            (
                ((cnt / size) / (overall[g] / n), g)
                for g, cnt in counts[c].items()
                if cnt / size >= MIN_GENRE_SHARE
            ),
            reverse=True,
        )

    taken: dict[str, tuple[float, int]] = {}  # genre -> (lift, section)
    pending = list(choices)
    while pending:
        c = pending.pop()
        while choices[c]:
            lift, g = choices[c].pop(0)
            if g not in taken:
                taken[g] = (lift, c)
                break
            if lift > taken[g][0]:  # stronger claim: bump the current holder
                pending.append(taken[g][1])
                taken[g] = (lift, c)
                break

    primary = {c: g for g, (_, c) in taken.items()}
    for c in counts:
        if c not in primary and counts[c]:
            primary[c] = counts[c].most_common(1)[0][0]

    names = {}
    for c, g in primary.items():
        members = [set(genres[i]) for i in np.flatnonzero(labels == c)]
        fit = sum(g in gs for gs in members) / len(members)
        name = SECTION_NAMES[g]
        if fit < COMPOUND_BELOW:
            covered = {
                h: sum(bool({g, h} & gs) for gs in members) / len(members)
                for h in counts[c]
                if h != g
            }
            if covered:
                second = max(covered, key=lambda h: (covered[h], h))
                if covered[second] >= fit + COMPOUND_GAIN:
                    name = f"{name} & {SECTION_NAMES[second]}"
        names[c] = name
    return names


def layout(matrix: np.ndarray, seed: int = 0) -> np.ndarray:
    """N x D vectors -> N x 2 positions in [-1, 1], aspect ratio preserved."""
    from sklearn.decomposition import PCA  # heavy imports; only the build step needs them
    from sklearn.manifold import TSNE

    n = len(matrix)
    if n < 3:
        return np.zeros((n, 2), dtype=np.float32)
    reduced = PCA(n_components=min(50, n - 1, matrix.shape[1]), random_state=seed).fit_transform(
        matrix
    )
    xy = TSNE(
        n_components=2,
        perplexity=max(1.0, min(30.0, (n - 1) / 3)),
        init="pca",
        random_state=seed,
    ).fit_transform(reduced)
    xy -= np.median(xy, axis=0)
    # Scale by a high percentile, not the max, so a few outliers don't shrink the map.
    scale = float(np.percentile(np.abs(xy), 99.5)) or 1.0
    return np.clip(xy / scale, -1.0, 1.0).astype(np.float32)


@dataclass
class MapNode:
    imdb_id: str
    title: str
    year: int | None
    poster_url: str | None
    x: float
    y: float
    section: int  # index into MovieMap.sections
    genres: list[str]  # the film's own IMDb genres (sections only name areas)


@dataclass
class Section:
    name: str
    size: int  # seats


@dataclass
class ExtraSeat:
    """A seat made on demand for a movie outside the house's seating."""

    imdb_id: str
    x: float
    y: float
    section: int
    links: list[int]  # indexes into MovieMap.nodes
    genres: list[str]


@dataclass
class MovieMap:
    ids: list[str]
    xy: np.ndarray  # N x 2, every mapped movie
    nodes: list[MapNode]  # seats, most-voted first; x, y on the grid
    edges: list[tuple[int, int]]  # indexes into nodes, i < j
    sections: list[Section]
    index: MovieIndex | None = None

    def __post_init__(self) -> None:
        self.row = {imdb_id: i for i, imdb_id in enumerate(self.ids)}
        self.seated = {n.imdb_id: i for i, n in enumerate(self.nodes)}
        self.cells: dict[Cell, int] = {
            (round(n.x / GRID), round(n.y / GRID)): n.section for n in self.nodes
        }
        # True map positions of the seats, for finding an extra movie's neighborhood.
        self.seat_true = np.array(
            [self.xy[self.row[n.imdb_id]] for n in self.nodes], dtype=np.float32
        ).reshape(-1, 2)

    def extra_seats(self, imdb_ids: list[str]) -> list[ExtraSeat]:
        """Seats for movies that don't have one (picks or results outside the house's
        seating): the free cell nearest the movie's true position, in the section of
        its nearest seat, linked to its most similar seats. Seated in request order,
        so earlier movies keep their spot when more are asked for. Movies already
        seated, or not on the map at all, are left out."""
        if not self.nodes:
            return []
        taken = dict(self.cells)
        out = []
        for imdb_id in imdb_ids:
            if imdb_id in self.seated or (pos := self.position(imdb_id)) is None:
                continue
            x, y = pos
            nearest = int(np.argmin(np.hypot(self.seat_true[:, 0] - x, self.seat_true[:, 1] - y)))
            section = self.nodes[nearest].section
            # Try to respect the aisles; squeeze in without them rather than not at all.
            cell = find_cell(x, y, section, taken, reach=EXTRA_REACH) or find_cell(
                x, y, section, taken, reach=EXTRA_REACH, aisle=1
            )
            if cell is None:
                continue
            taken[cell] = section
            sx, sy = round(cell[0] * GRID, 4), round(cell[1] * GRID, 4)
            genres = (
                self.index.features[self.index.row[imdb_id]].genres
                if self.index and imdb_id in self.index.row
                else []
            )
            out.append(ExtraSeat(imdb_id, sx, sy, section, self._links(imdb_id, sx, sy), genres))
        return out

    def _links(self, imdb_id: str, x: float, y: float) -> list[int]:
        """The extra seat's most similar seats: up to NEIGHBORS within link range, or
        just the single most similar one if none are that close."""
        index = self.index
        if index is None or imdb_id not in index.row:
            return []
        rows = [index.row.get(n.imdb_id) for n in self.nodes]
        known = [i for i, r in enumerate(rows) if r is not None]
        if not known:
            return []
        sims = index.matrix[[rows[i] for i in known]] @ index.matrix[index.row[imdb_id]]
        ranked = [known[k] for k in np.argsort(-sims)]
        close = [
            i
            for i in ranked[:20]
            if np.hypot(self.nodes[i].x - x, self.nodes[i].y - y) <= MAX_LINK_LENGTH
        ]
        return close[:NEIGHBORS] or ranked[:1]

    def position(self, imdb_id: str) -> tuple[float, float] | None:
        i = self.row.get(imdb_id)
        return None if i is None else (float(self.xy[i, 0]), float(self.xy[i, 1]))

    @classmethod
    def load(
        cls, eng: Engine, map_path: Path, index: MovieIndex | None, candidates: int
    ) -> "MovieMap":
        """`candidates`: how many of the most-voted movies compete for board space."""
        with np.load(map_path, allow_pickle=False) as npz:
            ids = [str(x) for x in npz["ids"]]
            xy = npz["xy"].astype(np.float32)
            saved = (
                ([str(x) for x in npz["section_ids"]], npz["section_labels"].astype(np.int64))
                if "section_ids" in npz.files
                else None
            )
        rows = {imdb_id: i for i, imdb_id in enumerate(ids)}

        with Session(eng) as s:
            movies = map_candidates(s, ids, candidates)
        true_xy = xy[[rows[m.imdb_id] for m in movies]].reshape(-1, 2)
        if saved and saved[0] == [m.imdb_id for m in movies]:
            labels = saved[1]  # precomputed by ingest/build_map.py; same result, no sklearn
        else:
            log.info("map sections not precomputed for these candidates; computing them")
            labels = split_sections(true_xy)
        cells = place_on_grid(true_xy, labels)
        seated = [
            (m, cell, int(lab)) for m, cell, lab in zip(movies, cells, labels, strict=True) if cell
        ]
        names = name_sections(
            np.array([lab for _, _, lab in seated], dtype=np.int64),
            [m.genre_list for m, _, _ in seated],
        )
        # Renumber the named sections 0..n-1, biggest first.
        sizes = Counter(lab for _, _, lab in seated if lab in names)
        order = {lab: i for i, (lab, _) in enumerate(sizes.most_common())}
        nodes = [
            MapNode(
                imdb_id=m.imdb_id,
                title=m.title,
                year=m.year,
                poster_url=poster_url(m.poster_path),
                x=round(cell[0] * GRID, 4),
                y=round(cell[1] * GRID, 4),
                section=order[lab],
                genres=m.genre_list,
            )
            for m, cell, lab in seated
            if lab in order
        ]
        sections = [
            Section(name=names[lab], size=sizes[lab])
            for lab, _ in sorted(order.items(), key=lambda kv: kv[1])
        ]
        edges = neighbor_edges([n.imdb_id for n in nodes], index) if index else []
        edges = [
            (a, b)
            for a, b in edges
            if np.hypot(nodes[a].x - nodes[b].x, nodes[a].y - nodes[b].y) <= MAX_LINK_LENGTH
        ]
        log.info(
            "movie map: %d mapped, %d of %d candidates seated, %d links, sections: %s",
            len(ids),
            len(nodes),
            len(movies),
            len(edges),
            ", ".join(f"{s.name} ({s.size})" for s in sections),
        )
        return cls(ids=ids, xy=xy, nodes=nodes, edges=edges, sections=sections, index=index)


def neighbor_edges(
    node_ids: list[str], index: MovieIndex, k: int = NEIGHBORS
) -> list[tuple[int, int]]:
    """Link each node to its k most similar nodes (cosine on recommender vectors)."""
    keep = [i for i, imdb_id in enumerate(node_ids) if imdb_id in index.row]
    if len(keep) < 2:
        return []
    vecs = index.matrix[[index.row[node_ids[i]] for i in keep]]
    sims = vecs @ vecs.T
    np.fill_diagonal(sims, -np.inf)
    k = min(k, len(keep) - 1)
    nearest = np.argpartition(-sims, k - 1, axis=1)[:, :k]
    pairs = {
        (min(keep[a], keep[b]), max(keep[a], keep[b])) for a in range(len(keep)) for b in nearest[a]
    }
    return sorted(pairs)
