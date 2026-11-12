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

Movie data: information courtesy of IMDb (https://www.imdb.com), used with permission for non-commercial use. This product uses the TMDB API but is not endorsed or certified by TMDB.
