from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", extra="ignore")

    data_dir: Path = REPO_ROOT / "data"
    database_url: str = f"sqlite:///{REPO_ROOT / 'data' / 'filmarbiter.db'}"
    tmdb_api_key: str = ""
    cors_origins: list[str] = ["http://localhost:5173"]

    # Catalog filter applied at IMDb ingest time.
    min_votes: int = 5000

    # Feature-block weights for the movie vectors (see ingest/build_vectors.py).
    # Overall similarity = sum(weight * block similarity), so weights should sum to 1.
    # Content blocks get 90%; era + language are a capped 10% bonus, never a filter.
    weight_overview: float = 0.405
    weight_keywords: float = 0.27
    weight_genres: float = 0.135
    weight_people: float = 0.09
    weight_era: float = 0.05
    weight_language: float = 0.05


settings = Settings()
