SHELL := /bin/zsh
export PATH := $(HOME)/.local/bin:$(PATH)

.PHONY: install api web test lint ingest

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

ingest:
	cd backend && uv run python -m ingest.imdb && uv run python -m ingest.tmdb && uv run python -m ingest.build_vectors
