# filmarbiter
App for helping people just pick a movie already.

- **Movie Blender:** pick 1–5 movies you like and get the 3 that best match all of them.
- **Use my Letterboxd:** enter a Letterboxd username and get picks based on how you've rated what you've already seen.

## Stack
- `backend/`: Python 3.12+ (FastAPI, SQLAlchemy + Alembic on SQLite, numpy/scikit-learn, sentence-transformers), managed with [uv](https://docs.astral.sh/uv/)
- `frontend/`: React + Vite + TypeScript + Tailwind, TanStack Query, React Router
- Data: IMDb non-commercial datasets (catalog), TMDB API (plot summaries, keywords, posters), Letterboxd public profiles via [`letterboxdpy`](https://github.com/nmcassa/letterboxdpy)

SQLite is for the MVP; the plan is Postgres at launch. Keep database code portable: SQLite-specific SQL (FTS5 title search) lives only in `backend/app/search.py`.

## Setup
Requires uv, Node LTS and a free [TMDB API key](https://www.themoviedb.org/settings/api).

```sh
cp .env.example .env   # then set TMDB_API_KEY
make install           # backend + frontend dependencies (~1.2 GB, mostly PyTorch)
make ingest            # build the catalog: see below
```

`make ingest` runs, in order:

| Step | Command | First run |
|---|---|---|
| Create/upgrade tables | `make migrate` | instant |
| IMDb catalog: feature films with 5,000+ votes (~19k) | `make ingest-imdb` | downloads ~1.4 GB to `data/imdb/`, then ~20 s |
| TMDB enrichment: overviews, keywords, posters | `make ingest-tmdb` | ~12 min; resumable, only fetches movies not yet enriched |
| Coverage report | `make report` | instant |
| Movie vectors for recommendations | `make vectors` | ~25 s; downloads the 90 MB MiniLM model once |
| 2D map of the vectors for the Blender's movie theater | `make map` | ~25 s |

Everything generated lives in `data/` (gitignored).

## Develop
```sh
make api    # FastAPI on http://localhost:8000 (loads data/vectors.npz at startup)
make web    # Vite on http://localhost:5173 (proxies /api to the backend)
make test   # backend tests
make lint   # ruff + oxlint
```

- **Restart `make api` after `make vectors` or `make map`**: both are loaded once at startup. Without vectors, blend and Letterboxd picks return 503 with a clear message; search still works. Without the map, the Blender hides its movie theater and works as a plain panel.
- **Schema changes:** edit `backend/app/models.py`, then `cd backend && uv run alembic revision --autogenerate -m "..."` and `make migrate`. Autogenerate ignores the hand-made FTS5 tables.
- **Refreshing data:** IMDb publishes new datasets daily. `cd backend && uv run python -m ingest.imdb --refresh` re-downloads them; re-ingesting keeps existing TMDB data. Then run `make ingest-tmdb` (new movies only) `make vectors` and `make map`, and restart the API.

### API
| Endpoint | Purpose |
|---|---|
| `GET /api/movies/search?q=` | Title autocomplete |
| `GET /api/movies/{imdb_id}` | Movie detail |
| `POST /api/blend` `{imdb_ids: [1..5]}` | Top 3 matches with reasons |
| `GET /api/map` | Movie theater: well-known films as seats on a grid (from the `MAP_CANDIDATES` most-voted, default 4000; crowded areas keep only their best-known), split by aisles into ~10 sections named after their most distinctive genre (two genres for mixed sections, e.g. "COMEDY & DRAMA"), with each film's own genres and links to similar films |
| `GET /api/map/seats?ids=` | Seats made for up to 20 films without one (picks or results), next to where they belong, with their section and links; send picks before results so earlier seats stay put |
| `GET /api/letterboxd/verify/{username}` | `ok` / `not_found` / `private` / `invalid`; 503 if Letterboxd is down |
| `POST /api/letterboxd/import` `{username, refresh?}` | Start (or reuse) an import of a verified user; 409 if not verified |
| `GET /api/letterboxd/import/{job_id}` | Import status and phase |
| `GET /api/letterboxd/{username}/recommendations?limit=` | Picks with "because you rated" and reasons |

Interactive docs at http://localhost:8000/docs while `make api` is running.

## Letterboxd integration
Letterboxd has no open API, so `backend/app/letterboxd/client.py` wraps `letterboxdpy`, which reads public profile pages. Everything Letterboxd-specific is behind that file, so it can be swapped for a CSV-export upload or the official API.

- **Only public profiles.** No login; private profiles get a clear "private" message.
- **Flow:** verify the username (one profile request, capped at 15 s, cached 1 h), then a background import pages through the user's films (~0.25 s between pages), matches them to the catalog, and stores them. Imports under 24 h old are reused unless the user refreshes.
- **Matching:** normalised title + year, then subtitle ("Star Wars: The Last Jedi" ↔ "Star Wars: Episode VIII - The Last Jedi"), then a few capped lookups of the film's IMDb link on Letterboxd (cached). On a 3,485-film profile, 2,483 matched in ~35 s; nearly all the rest are outside the catalog.
- **Fragility:** this is scraping, so Letterboxd markup changes can break it, and its Cloudflare protection occasionally slows or blocks requests (a verify can take ~8 s, or fail and ask the user to retry). Scraping is a grey area under Letterboxd's terms; revisit before launch.
- **Single-process assumptions:** the verify cache is in memory, and imports run as FastAPI background tasks. A job left "running" by a restart blocks that user until it's 30 min old; the next import request then marks it "interrupted" and starts fresh. Scaling out needs a shared cache and a job queue.

## How recommendations work
Code: `backend/app/recommender/` (features → index → engine); vectors are built by `make vectors`.

Each movie is turned into one vector (~760 numbers), and similarity is cosine similarity between vectors. The vector joins six blocks, each scaled to unit length and then by √weight, so that **overall similarity = Σ weight × block similarity**. Content gets 90% of the weight; era and language together get 10%.

| Block | Source | Captures | Weight |
|---|---|---|---|
| Overview | TMDB plot summary → MiniLM sentence embedding (384-d) | story / premise | 0.405 |
| Keywords | TMDB tags → TF-IDF → SVD (128-d) | themes / tone | 0.27 |
| Genres | IMDb genres, TF-IDF weighted | broad category | 0.135 |
| People | directors, writers, top-5 cast → TF-IDF → SVD (128-d) | authorship | 0.09 |
| Era | release year, smooth encoding (similarity ≈ 68% at 10 years apart, ≈ 21% at 20) | period | 0.05 |
| Language | TMDB original language, one-hot | language | 0.05 |

- **Era and language are a capped bonus, never a filter.** A full mismatch costs at most 0.10, so a movie from any era or language still wins if its content similarity is about 0.11 higher (0.10 ÷ 0.90). Mixed picks (a 1950s Japanese film plus a 2010s American one) split that signal, so it barely pushes in any direction.
- **TF-IDF** makes rare tags count more (*heist*, 157 movies, outweighs *murder*, 1,149 movies). **SVD** puts tags that co-occur close together, so *robbery* partly matches *hold-up robbery*.
- Titles aren't used, so *The Heat* doesn't match *Heat*. Tags about the release rather than the film (*duringcreditsstinger*, *sequel*, *woman director*…) are ignored; see `IGNORED_KEYWORDS` in `features.py`.
- If a block is missing (no keywords for ~8% of movies), the remaining blocks share the score.
- Weights live in `backend/app/config.py`. The matrix (~50 MB) is held in memory and brute-force search takes milliseconds, so there's no vector DB.

**Blender** (1–5 picks → top 3): `0.7 × similarity to the average of the picks + 0.3 × lowest similarity to any single pick`, so results fit every pick. Then:
1. Multiply by a quality factor (0.5–1.0, from IMDb rating and votes).
2. Exclude the picks and their sequels (TMDB collection).
3. Choose the 3 results with MMR so they aren't near-duplicates.

Each result's "why" line lists keywords, genres and people it shares with the picks.

**Letterboxd:** taste vector = Σ (rating − the user's average rating) × movie vector, with a small bonus for ♥ likes; below-average ratings count at half strength. Logged films are excluded, then a stronger quality factor (0.4–1.0; a big profile averages into a blander vector) and MMR apply. Each result cites the user's liked films most similar to it ("because you rated…"), avoiding citing the same favourites on every pick; its "why" line draws on their 25 most related liked films.

### Tuning
```sh
cd backend && uv run python -m scripts.eval_recs [--letterboxd USER] [-v]
```
Scores 8 check blends against hand-picked expected films (hits in the top 10) and reports the mean IMDb rating of what users would see; with `--letterboxd` it also scores that user's imported picks. Try block weights (`--weights people=0.2,...`) or quality floors (`--quality-floor 0.6`) without rebuilding vectors. Check the printed lists too: the hit count can't tell when results drift toward generically famous films.

The current settings came from it: lowering the quality floor from 0.85 took expected-film hits from 18 to 23 of 69 and Letterboxd picks from 6.8 to 7.5 IMDb; block-weight changes made no measurable difference, so the weights are unchanged.

**Known gaps:** "vibe" that lives in a studio's style rather than plot, tags or people (A24 folk horror) isn't captured: that check blend scores 1/10. Mood-driven blends can match on premise instead (Before Sunrise + Lost in Translation suggests *The Ramen Girl*). Blends of two very different films are inherently harder.

## Data and attribution
Information courtesy of IMDb (https://www.imdb.com), used with permission for non-commercial use. This product uses the TMDB API but is not endorsed or certified by TMDB. The site footer carries the same notice.
