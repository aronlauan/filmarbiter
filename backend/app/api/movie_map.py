from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from app.recommender.movie_map import GRID, MovieMap
from app.recommender.state import get_map
from app.schemas import MapNodeOut, MapResponse, MapSeat, MapSection

router = APIRouter(prefix="/api/map", tags=["map"])

MapDep = Annotated[MovieMap, Depends(get_map)]

MAX_SEATS = 20


@router.get("", response_model=MapResponse)
def movie_map(m: MapDep) -> MapResponse:
    return MapResponse(
        grid=GRID,
        nodes=[MapNodeOut(**n.__dict__) for n in m.nodes],
        edges=m.edges,
        sections=[MapSection(**s.__dict__) for s in m.sections],
    )


@router.get("/seats", response_model=list[MapSeat])
def seats(
    m: MapDep, ids: Annotated[str, Query(min_length=1, max_length=MAX_SEATS * 12)]
) -> list[MapSeat]:
    """Seats for movies without one (picks or results outside the house's seating),
    next to where they belong. Order matters: earlier ids keep their seat when more
    are added, so send picks before results. Movies already seated, or not on the
    map, are left out."""
    wanted = list(dict.fromkeys(i for i in ids.split(",") if i))
    if len(wanted) > MAX_SEATS:
        raise HTTPException(status_code=422, detail=f"At most {MAX_SEATS} ids")
    return [MapSeat(**seat.__dict__) for seat in m.extra_seats(wanted)]
