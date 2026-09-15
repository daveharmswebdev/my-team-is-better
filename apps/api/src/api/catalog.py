"""`/api/years`, `/api/teams`, and `/api/credits` -- issue #13/#29's
evidence-catalog routes.

`/api/years` and `/api/teams` back `apps/web`'s year/team picker fields (PRD
§5.1: "`list_seasons` / `list_available_years` backs the year picker so
users can only select years that are actually ingested"). `/api/credits`
backs issue #29's "How this works / Credits" page. Unlike `api.verdict`'s
routes, all three return plain evidence-catalog data -- no persona
narration envelope, no MCP -- so each route is a thin call straight into
`cfb_strength.evidence.proof` (years), `api.repositories.teams.
list_team_records` (teams), or `cfb_strength.evidence.credits` (credits), with no
business logic of its own. `/api/credits` needs no db connection at all
(unlike the other two): `get_credits()` takes no arguments and touches no
database, so this route has no `Depends(get_db_conn)`.
"""

from __future__ import annotations

import sqlite3

from cfb_strength.evidence.credits import get_credits
from cfb_strength.evidence.proof import list_available_years
from fastapi import APIRouter, Depends

from api.deps import get_db_conn
from api.models import CreditsOut, Method, Sport, TeamDetailOut, TeamsOut, YearsOut
from api.repositories.teams import list_team_records

router = APIRouter(prefix="/api", tags=["catalog"])


@router.get("/years", response_model=YearsOut)
def years(
    method: Method = "keener",
    sport: Sport = "cfb",
    conn: sqlite3.Connection = Depends(get_db_conn),
) -> YearsOut:
    """Distinct years with ratings under `method`/`sport`, ascending -- the
    year picker's valid-selection universe. `sport` defaults to "cfb"
    (issue #59), matching today's behavior for a client that never sends it.

    `method` is constrained to the registered methods (`api.models.Method`),
    so an unknown one is a 422 rather than an empty list. This route is the
    one that most needed it: an empty `years` array is a legitimate answer
    here (a method that exists but has not been computed), so before the
    constraint a typo'd method rendered as an empty year picker that looked
    exactly like an un-ingested season.
    """
    return YearsOut(years=list_available_years(conn, method, sport))


@router.get("/teams", response_model=TeamsOut)
def teams(
    sport: Sport = "cfb",
    year: int | None = None,
    method: Method = "keener",
    conn: sqlite3.Connection = Depends(get_db_conn),
) -> TeamsOut:
    """The team picker's valid-selection universe for `sport`, optionally
    narrowed to one season.

    With `year` (issue #78), only teams that actually have a
    `year`/`sport`/`method` rating are offered -- without it, an NFL picker
    offers both halves of every relocation ("Las Vegas Raiders" for a 2010
    question, "San Diego Chargers" for a 2024 one, neither of which has
    data for that year) and a CFB picker offers the entire ~788-name
    FBS/FCS/D2/D3 opponent universe the games ingest has ever seen. An
    un-ingested year is an empty list with HTTP 200, not an error: this
    route populates a picker, it doesn't resolve a verdict.

    `sport` defaults to "cfb" (issue #59) and `method` to "keener"
    (matching `/api/years` above); omitting `year` returns exactly the
    pre-#78 full per-sport list, so a client that never sends it sees no
    change. `method` is likewise constrained to the registered methods --
    an unknown one is a 422, not a silently empty team list. Note it only
    narrows anything when `year` is given, since the unscoped list joins no
    ratings rows; it is still validated in both cases, so a typo cannot be
    accepted by one route and rejected by the other.

    `team_details` is additive metadata for the same teams in the same
    order -- see `api.models.TeamsOut`. Both arrays come from the one
    `list_team_records` call below, never two queries, so they cannot drift
    apart.

    Note this is `list_team_records`, not the grounding check's
    `list_all_team_names`: the persona layer's known-team-name universe
    must stay unscoped (see `api.repositories.teams`).
    """
    records = list_team_records(conn, sport=sport, year=year, method=method)
    return TeamsOut(
        teams=[record.name for record in records],
        team_details=[
            TeamDetailOut(name=record.name, mascot=record.mascot, aliases=list(record.aliases))
            for record in records
        ],
    )


@router.get("/credits", response_model=CreditsOut)
def credits() -> CreditsOut:
    """The project's attribution data -- a methodology citation for every
    rating method the engine implements (Keener's method and Elo, in that
    order) plus both data-source credits (CollegeFootballData.com for CFB,
    nflverse/Lee Sharpe for NFL, issue #59).

    Deliberately not filtered by the `method` a caller happens to be
    querying with: this backs the About page, which credits the whole basis
    of the rankings, and `get_credits()` correspondingly takes no arguments.
    No db connection either -- the single source of truth
    (`cfb_strength.evidence.credits.get_credits()`) is static content, not a
    db read."""
    return CreditsOut.from_dataclass(get_credits())
