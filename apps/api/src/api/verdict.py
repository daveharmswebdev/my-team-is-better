"""`/api/verdict` routes -- PRD §5.1's three structured question types.

Each route calls the matching `cfb_strength.evidence.proof` function
directly (no MCP, no LLM, no narration -- that's issue #4) and returns the
raw evidence via the Pydantic response models in `api.models`. Typed engine
exceptions (`UnknownYearError`, `AmbiguousTeamError`, `SameTeamComparisonError`)
propagate up to the app-level exception handlers registered in
`api.errors` -- routes never catch them themselves, so there is exactly one
place the exception -> HTTP mapping is spelled out (Architecture Brief §4.4).

Question type 1 ("who was the best team in <year>?") has no `get_champion`
in the evidence layer -- only `cfb_strength.mcp_server.server.get_champion`,
which this app must not import (it's the MCP/LLM-tool surface, wraps results
in `{"error": ...}` dicts rather than raising, wrong shape for HTTP). Per
issue #3's brief, `_resolve_champion_name` below replicates that same
7-line rank=1 SQL query directly against the connection this app already
holds, then hands the resolved name to `build_team_case` -- the only
non-evidence-layer SQL in this app, by design.
"""

from __future__ import annotations

import sqlite3

from cfb_strength.evidence.proof import build_comparison, build_team_case
from fastapi import APIRouter, Depends

from api.deps import get_db_conn
from api.models import (
    ChampionRequest,
    ComparisonRequest,
    ComparisonResultOut,
    TeamCaseOut,
    TeamCaseRequest,
)

router = APIRouter(prefix="/api/verdict", tags=["verdict"])


def _resolve_champion_name(conn: sqlite3.Connection, year: int, method: str) -> str | None:
    row = conn.execute(
        """
        SELECT t.school AS school
        FROM ratings r
        JOIN teams t ON t.id = r.team_id
        WHERE r.year = ? AND r.method = ? AND r.rank = 1
        """,
        (year, method),
    ).fetchone()
    return str(row["school"]) if row is not None else None


@router.post("/champion", response_model=TeamCaseOut)
def champion(
    payload: ChampionRequest, conn: sqlite3.Connection = Depends(get_db_conn)
) -> TeamCaseOut:
    """'Who was the best team in <year>?' -- resolve the #1-ranked team, then
    return its full evidentiary case (same shape as /team-case)."""
    name = _resolve_champion_name(conn, payload.year, payload.method)
    # `name is None` (no ratings rows at all for year/method) still needs to
    # surface as UnknownYearError -- build_team_case raises it for us as
    # soon as resolve_team's `_require_year` check runs, whether we pass a
    # real name or any placeholder query string.
    case = build_team_case(conn, payload.year, name or "", method=payload.method)
    return TeamCaseOut.from_dataclass(case)


@router.post("/team-case", response_model=TeamCaseOut)
def team_case(
    payload: TeamCaseRequest, conn: sqlite3.Connection = Depends(get_db_conn)
) -> TeamCaseOut:
    """'How good was <team> in <year>?'"""
    case = build_team_case(conn, payload.year, payload.team, method=payload.method)
    return TeamCaseOut.from_dataclass(case)


@router.post("/compare", response_model=ComparisonResultOut)
def compare(
    payload: ComparisonRequest, conn: sqlite3.Connection = Depends(get_db_conn)
) -> ComparisonResultOut:
    """'Was <team_a> better than <team_b> in <year>?'"""
    comparison = build_comparison(
        conn, payload.year, payload.team_a, payload.team_b, method=payload.method
    )
    return ComparisonResultOut.from_dataclass(comparison)
