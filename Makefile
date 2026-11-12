SHELL := /bin/zsh
export PATH := $(HOME)/.local/bin:$(PATH)

.PHONY: install api web test lint migrate ingest ingest-imdb ingest-tmdb report vectors

install:
	cd backend && uv sync
	cd frontend && npm install

api:
	cd backend && uv run uvicorn app.main:app --reload --port 8000

web:
	cd frontend && npm run dev

test:
	cd backend && uv run pytest -q

lint:
	cd backend && uv run ruff check . && uv run ruff format --check .
	cd frontend && npm run lint

migrate:
	cd backend && uv run alembic upgrade head

# Full catalog build: IMDb -> TMDB enrichment -> coverage report -> movie vectors.
# Restart the API afterwards so it loads the new vectors.
ingest: migrate ingest-imdb ingest-tmdb report vectors

ingest-imdb:
	cd backend && uv run python -m ingest.imdb

# Resumable; only fetches movies not yet enriched. Needs TMDB_API_KEY in .env.
ingest-tmdb:
	cd backend && uv run python -m ingest.tmdb

report:
	cd backend && uv run python -m ingest.report

vectors:
	cd backend && uv run python -m ingest.build_vectors
