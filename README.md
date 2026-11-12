# filmarbiter
App for helping people just pick a movie already.

## Stack
- `backend/`: Python (FastAPI, SQLAlchemy/SQLite), managed with [uv](https://docs.astral.sh/uv/)
- `frontend/`: React + Vite + TypeScript + Tailwind

## Setup
Requires uv and Node LTS.

```sh
cp .env.example .env   # add your TMDB API key
make install           # backend + frontend deps
make ingest            # build the movie catalog (IMDb datasets + TMDB enrichment)
```

## Develop
```sh
make api    # FastAPI on http://localhost:8000
make web    # Vite on http://localhost:5173 (proxies /api to the backend)
make test   # backend tests
make lint
```

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

- **Era and language are a capped bonus, never a filter.** A full mismatch costs at most 0.10, so a movie from any era or language still wins if its content similarity is about 0.11 higher (0.10 ÷ 0.90).
- Mixed picks (e.g. a 1950s Japanese film plus a 2010s American one) split the era/language signal, so it barely pushes in any direction. For Letterboxd, the user's rating history sets the preference.

- **TF-IDF** makes rare tags count more (*heist*, 157 movies, outweighs *murder*, 1,149 movies). **SVD** puts tags that co-occur close together, so *robbery* partly matches *hold-up robbery*.
- Titles aren't used, so *The Heat* doesn't match *Heat*.
- Tags about the release rather than the film (*duringcreditsstinger*, *sequel*, *woman director*…) are ignored; see `IGNORED_KEYWORDS` in `features.py`.
- If a block is missing (no keywords for ~8% of movies), the remaining blocks share the score.
- Weights live in `backend/app/config.py`. The matrix (~50 MB) is held in memory, and brute-force search takes milliseconds, so there's no vector DB.

**Blender** (1–5 picks → top 3): `0.7 × similarity to the average of the picks + 0.3 × lowest similarity to any single pick`, so results fit every pick. Then:
1. Multiply by a quality factor (0.85–1.0, from IMDb rating and votes).
2. Exclude the picks and their sequels (TMDB collection).
3. Choose the 3 results with MMR so they aren't near-duplicates.

**Letterboxd:** taste vector = Σ (rating − the user's average rating) × movie vector, with a small bonus for ♥ likes. Logged films are excluded, then the same quality factor and MMR steps apply.

Each result carries a "why" line built from shared keywords, genres and people.

**Known gaps:** weights are initial guesses, to be checked against a fixed set of test blends.

Movie data: information courtesy of IMDb (https://www.imdb.com), used with permission for non-commercial use. This product uses the TMDB API but is not endorsed or certified by TMDB.
