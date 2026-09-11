"""`/api/years`, `/api/teams`, and `/api/credits` -- issue #13/#29's
evidence-catalog routes.

`/api/years` and `/api/teams` back `apps/web`'s year/team picker fields (PRD
§5.1: "`list_seasons` / `list_available_years` backs the year picker so
users can only select years that are actually ingested"). `/api/credits`
backs issue #29's "How this works / Credits" page. Unlike `api.verdict`'s
routes, all three return plain evidence-catalog data -- no persona
narration envelope, no MCP -- so each route is a thin call straight into
`cfb_strength.evidence.proof` (years), the shared `api.deps.list_all_team_names`
helper (teams), or `cfb_strength.evidence.credits` (credits), with no
business logic of its own. `/api/credits` needs no db connection at all
(unlike the other two): `get_credits()` takes no arguments and touches no
database, so this route has no `Depends(get_db_conn)`.
"""

from __future__ import annotations

import sqlite3

from cfb_strength.evidence.credits import get_credits
from cfb_strength.evidence.proof import list_available_years
from fastapi import APIRouter, Depends

from api.deps import get_db_conn, list_all_team_names
from api.models import CreditsOut, TeamsOut, YearsOut

router = APIRouter(prefix="/api", tags=["catalog"])


@router.get("/years", response_model=YearsOut)
def years(
    method: str = "keener",
    conn: sqlite3.Connection = Depends(get_db_conn),
) -> YearsOut:
    """Distinct years with ratings under `method`, ascending -- the year
    picker's valid-selection universe."""
    return YearsOut(years=list_available_years(conn, method))


@router.get("/teams", response_model=TeamsOut)
def teams(conn: sqlite3.Connection = Depends(get_db_conn)) -> TeamsOut:
    """Every team name in the db -- the team picker's valid-selection
    universe, the same query the persona grounding check already uses."""
    return TeamsOut(teams=list_all_team_names(conn))


@router.get("/credits", response_model=CreditsOut)
def credits() -> CreditsOut:
    """The project's attribution data -- Keener methodology citation +
    CollegeFootballData.com data source credit. No db connection: the
    single source of truth (`cfb_strength.evidence.credits.get_credits()`)
    is static content, not a db read."""
    return CreditsOut.from_dataclass(get_credits())
