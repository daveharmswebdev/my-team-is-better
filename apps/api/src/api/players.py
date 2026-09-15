"""`/api/players/leaders` and `/api/players/{player_id}` -- issue #296's
player read layer over HTTP, backing apps/web's sortable leaders page and a
player's career page.

Like `api.catalog`, both routes are a thin call straight into the engine
(`cfb_strength.players`) with no business logic of their own: the response
models in `api.models` copy the engine dataclasses field for field, and
nothing here re-sorts, re-ranks or fills a null stat with 0. What this
module adds is only the HTTP boundary:

- **Bounds are request validation.** `limit` (1..`PLAYER_LEADERS_MAX_LIMIT`)
  and `offset` (0..`SQLITE_INTEGER_MAX`) are FastAPI `Query` bounds, so an
  out-of-range value is a 422 located at that field before the engine is
  called. The engine's own `ValueError` for the same bounds must never
  surface as a 500, and neither may sqlite3's `OverflowError` for an offset
  no SQLite INTEGER can hold (#296 review).
- **Only leagues with player stats.** CFB has none, so `sport=cfb` would
  answer an empty 200 that looks exactly like an unloaded db (the failure
  #104 fixed for `method`). `player_sport` turns it into a 422 at `sport`
  with FastAPI's own validation shape instead. The published enum is still
  the contract's whole `Sport`, not `["nfl"]`: `api.models` must not spell
  out a narrower `Literal` (tests/test_openapi_vocabularies.py forbids a
  local vocabulary, and apps/web checks one `sport` enum). Publishing the
  narrower set needs a contract alias for "leagues with player stats".
- **An unknown player is a typed 404** (`unknown_player`, mapped in
  `api.errors`). That includes an id no SQLite INTEGER can hold, which
  would otherwise reach sqlite3 and raise an unmapped `OverflowError` as a
  500 -- the same "echo what was asked" rule #189 set for season years.
"""

from __future__ import annotations

import sqlite3
from typing import Annotated, Final

from cfb_strength.contracts import (
    PLAYER_LEADERS_MAX_LIMIT,
    PlayerLeaderSort,
    PlayerSeasonType,
    UnknownPlayerError,
)
from cfb_strength.players import get_player_career, get_player_leaders
from fastapi import APIRouter, Depends, Query
from fastapi.exceptions import RequestValidationError

from api.deps import get_db_conn
from api.errors import PLAYER_CAREER_ERROR_RESPONSES
from api.models import PlayerCareerOut, PlayerLeadersOut, Sport

router = APIRouter(prefix="/api", tags=["players"])

# The leagues whose player stats the engine ingests (`cfb ingest-players`
# accepts only these). A subset of `Sport`, checked at runtime; see the
# module docstring for why it is not a narrower published enum.
PLAYER_SPORTS: Final[frozenset[Sport]] = frozenset({"nfl"})

# SQLite INTEGER is a signed 64-bit value; `players.id` can hold nothing else.
SQLITE_INTEGER_MIN: Final = -(2**63)
SQLITE_INTEGER_MAX: Final = 2**63 - 1


def player_sport(sport: Sport = "nfl") -> Sport:
    """The `sport` query parameter of both player routes: any `Sport` passes
    the published enum, and one without player stats is rejected here as a
    request-validation 422 located at `sport`, in pydantic's `literal_error`
    shape, so a client handles it exactly like any other bad value."""
    if sport not in PLAYER_SPORTS:
        expected = " or ".join(repr(s) for s in sorted(PLAYER_SPORTS))
        raise RequestValidationError(
            [
                {
                    "type": "literal_error",
                    "loc": ("query", "sport"),
                    "msg": f"Input should be {expected}",
                    "input": sport,
                    "ctx": {"expected": expected},
                }
            ]
        )
    return sport


@router.get("/players/leaders", response_model=PlayerLeadersOut)
def leaders(
    sport: Annotated[Sport, Depends(player_sport)],
    season_type: PlayerSeasonType = "regular",
    sort: PlayerLeaderSort = "passing_yards",
    limit: Annotated[int, Query(ge=1, le=PLAYER_LEADERS_MAX_LIMIT)] = 50,
    offset: Annotated[int, Query(ge=0, le=SQLITE_INTEGER_MAX)] = 0,
    conn: sqlite3.Connection = Depends(get_db_conn),
) -> PlayerLeadersOut:
    """One page of a career leaderboard, always descending on `sort`, with
    `total` the size of the whole qualifying population so a client can
    page. `rank` is the engine's competition rank over that population
    (ties share it), null when the sort value is null."""
    return PlayerLeadersOut.from_dataclass(
        get_player_leaders(
            conn, sport=sport, season_type=season_type, sort=sort, limit=limit, offset=offset
        )
    )


@router.get(
    "/players/{player_id}",
    response_model=PlayerCareerOut,
    responses=PLAYER_CAREER_ERROR_RESPONSES,
)
def career(
    player_id: int,
    sport: Annotated[Sport, Depends(player_sport)],
    conn: sqlite3.Connection = Depends(get_db_conn),
) -> PlayerCareerOut:
    """A player's season lines (chronological, regular before postseason)
    with regular-season and postseason totals; `unknown_player` 404 when no
    player has that id in `sport`."""
    if not SQLITE_INTEGER_MIN <= player_id <= SQLITE_INTEGER_MAX:
        raise UnknownPlayerError(player_id, sport)
    return PlayerCareerOut.from_dataclass(get_player_career(conn, sport=sport, player_id=player_id))
