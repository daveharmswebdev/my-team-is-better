"""`/api/players/*` -- the player read layer over HTTP: issue #296's
`/api/players/leaders` and `/api/players/{player_id}`, backing apps/web's
sortable leaders page and a player's career page, and issue #301's
`/api/players/compare` and `/api/players/search`, backing the QB comparison.

Like `api.catalog`, every route is a thin call straight into the engine
(`cfb_strength.players`) with no business logic of their own: the response
models in `api.models` copy the engine dataclasses field for field, and
nothing here re-sorts, re-ranks, fills a null stat with 0, or compares one
player's numbers with another's. What this module adds is only the HTTP
boundary:

- **Bounds are request validation.** `limit` (1..`PLAYER_LEADERS_MAX_LIMIT`
  or 1..`PLAYER_SEARCH_MAX_LIMIT`) and `offset` (0..`SQLITE_INTEGER_MAX`)
  are FastAPI `Query` bounds, so an out-of-range value is a 422 located at
  that field before the engine is called. The engine's own `ValueError` for
  the same bounds must never surface as a 500, and neither may sqlite3's
  `OverflowError` for an offset no SQLite INTEGER can hold (#296 review).
  Two engine rules no `Query` bound can express are checked in the route
  and raised in FastAPI's own validation shape: search's `q` must keep
  `PLAYER_SEARCH_MIN_QUERY_LENGTH` characters *after stripping* (`' a '`
  passes `min_length`), located at `q`; and compare's `a` and `b` must be
  different players, located at `b`.
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
  Compare checks `a`'s range, then `b`'s, before the engine looks either up.
- **Fixed paths before `/players/{player_id}`.** Starlette matches routes in
  declaration order, so `leaders`, `compare` and `search` are declared first;
  below it they would be parsed as a non-integer `player_id` and 422.
"""

from __future__ import annotations

import sqlite3
from typing import Annotated, Final

from cfb_strength.contracts import (
    PLAYER_LEADERS_MAX_LIMIT,
    PLAYER_SEARCH_MAX_LIMIT,
    PLAYER_SEARCH_MIN_QUERY_LENGTH,
    PlayerLeaderSort,
    PlayerSeasonType,
    UnknownPlayerError,
)
from cfb_strength.players import (
    get_player_career,
    get_player_comparison,
    get_player_leaders,
    search_players,
)
from fastapi import APIRouter, Depends, Query
from fastapi.exceptions import RequestValidationError

from api.deps import get_db_conn
from api.errors import PLAYER_CAREER_ERROR_RESPONSES, PLAYER_COMPARISON_ERROR_RESPONSES
from api.models import (
    PlayerCareerOut,
    PlayerComparisonOut,
    PlayerLeadersOut,
    PlayerSearchOut,
    Sport,
)

router = APIRouter(prefix="/api", tags=["players"])

# The leagues whose player stats the engine ingests (`cfb ingest-players`
# accepts only these). A subset of `Sport`, checked at runtime; see the
# module docstring for why it is not a narrower published enum.
PLAYER_SPORTS: Final[frozenset[Sport]] = frozenset({"nfl"})

# SQLite INTEGER is a signed 64-bit value; `players.id` can hold nothing else.
SQLITE_INTEGER_MIN: Final = -(2**63)
SQLITE_INTEGER_MAX: Final = 2**63 - 1

# The longest search query accepted. HTTP-only: the engine sets no maximum,
# and a name is never this long.
PLAYER_SEARCH_MAX_QUERY_LENGTH: Final = 100


def player_sport(sport: Sport = "nfl") -> Sport:
    """The `sport` query parameter of every player route: any `Sport` passes
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


def _require_storable_player_id(player_id: int, sport: Sport) -> None:
    """An id no SQLite INTEGER can hold names no player: the typed 404,
    raised before sqlite3 can turn it into an unmapped `OverflowError`."""
    if not SQLITE_INTEGER_MIN <= player_id <= SQLITE_INTEGER_MAX:
        raise UnknownPlayerError(player_id, sport)


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
    "/players/compare",
    response_model=PlayerComparisonOut,
    responses=PLAYER_COMPARISON_ERROR_RESPONSES,
)
def compare(
    a: int,
    b: int,
    sport: Annotated[Sport, Depends(player_sport)],
    conn: sqlite3.Connection = Depends(get_db_conn),
) -> PlayerComparisonOut:
    """Two players' careers (each exactly their career page) and their
    regular-season and postseason head-to-head as opposing QB starters,
    with `a`'s W-L-T against `b` and the games in chronological order. Both
    head-to-heads are always present, 0-0-0 when the two never met.
    `unknown_player` 404 for the first of `a`, `b` with no player in `sport`;
    `a == b` is a 422 at `b`."""
    if a == b:
        raise RequestValidationError(
            [
                {
                    "type": "value_error",
                    "loc": ("query", "b"),
                    "msg": "Value error, b must be a different player from a",
                    "input": b,
                }
            ]
        )
    _require_storable_player_id(a, sport)
    _require_storable_player_id(b, sport)
    return PlayerComparisonOut.from_dataclass(get_player_comparison(conn, sport=sport, a=a, b=b))


@router.get("/players/search", response_model=PlayerSearchOut)
def search(
    q: Annotated[
        str,
        Query(min_length=PLAYER_SEARCH_MIN_QUERY_LENGTH, max_length=PLAYER_SEARCH_MAX_QUERY_LENGTH),
    ],
    sport: Annotated[Sport, Depends(player_sport)],
    limit: Annotated[int, Query(ge=1, le=PLAYER_SEARCH_MAX_LIMIT)] = 10,
    conn: sqlite3.Connection = Depends(get_db_conn),
) -> PlayerSearchOut:
    """Players whose name contains `q` (case-insensitive, literal), in the
    engine's order: regular-season passing yards descending, then name, then
    id. `query` echoes `q` stripped; no match is a 200 with no rows. A `q`
    under two characters once stripped is a 422 at `q`."""
    if len(q.strip()) < PLAYER_SEARCH_MIN_QUERY_LENGTH:
        raise RequestValidationError(
            [
                {
                    "type": "string_too_short",
                    "loc": ("query", "q"),
                    "msg": (
                        f"String should have at least {PLAYER_SEARCH_MIN_QUERY_LENGTH} "
                        "characters after stripping surrounding whitespace"
                    ),
                    "input": q,
                    "ctx": {"min_length": PLAYER_SEARCH_MIN_QUERY_LENGTH},
                }
            ]
        )
    return PlayerSearchOut.from_dataclass(search_players(conn, sport=sport, query=q, limit=limit))


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
    _require_storable_player_id(player_id, sport)
    return PlayerCareerOut.from_dataclass(get_player_career(conn, sport=sport, player_id=player_id))
