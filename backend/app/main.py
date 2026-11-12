import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from app.api import blend, letterboxd, movie_map, movies
from app.config import settings
from app.recommender.state import load_index, load_map

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    load_index()
    load_map()
    yield


app = FastAPI(title="filmarbiter", lifespan=lifespan)
app.include_router(movies.router)
app.include_router(blend.router)
app.include_router(movie_map.router)
app.include_router(letterboxd.router)

# The movie map is a few hundred KB of JSON; compresses ~4x.
app.add_middleware(GZipMiddleware, minimum_size=1024)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
