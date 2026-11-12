SHELL := /bin/zsh
export PATH := $(HOME)/.local/bin:$(PATH)

.PHONY: install api web test lint migrate ingest ingest-imdb

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

# Full catalog build. TMDB enrichment and vector build steps are added in later milestones.
ingest: migrate ingest-imdb

ingest-imdb:
	cd backend && uv run python -m ingest.imdb
