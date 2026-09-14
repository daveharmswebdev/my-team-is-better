"""`/api/verdict` routes -- PRD §5.1's three structured question types.

Each route calls the matching `cfb_strength.evidence.proof` function
directly (no MCP) and returns the raw evidence wrapped in issue #4's
persona narration envelope (`{"evidence": ..., "narration": ...}` --
`api.models.TeamCaseEnvelope`/`ComparisonEnvelope`). The evidence half is
unchanged from issue #3; narration is computed by
`api.persona.service.narrate_team_case`/`narrate_comparison`, which handles
the cache lookup, the Claude call, and the grounding retry/fallback. Typed
engine exceptions (`UnknownYearError`, `UnknownTeamError`,
`AmbiguousTeamError`, `SameTeamComparisonError`) propagate up to the
app-level exception handlers registered in `api.errors` -- routes never
catch them themselves, so there is exactly one place the exception -> HTTP
mapping is spelled out (Architecture Brief §4.4). `UnknownTeamError` (issue
#100) is the newest of the four: a team query that matches *no* rated team
for the requested year/sport, which the engine used to conflate with
`AmbiguousTeamError`.

Because routes never raise those exceptions directly, FastAPI cannot infer
them for `/openapi.json`, so each route declares them via `responses=` using
the prebuilt sets in `api.errors` (issue #111). Pick the set that matches
the engine function the route calls (`build_team_case` or
`build_comparison`). For every route in the app,
tests/test_openapi_error_responses.py works out which handled engine
exceptions the endpoint can reach by following the functions it references.
It fails if the route's declaration does not accept a reachable exception's
real handler response, or advertises one the route cannot reach. That test's
docstring lists the call paths it cannot follow.

Question type 1 ("who was the best team in <year>?") has no `get_champion`
in the evidence layer -- only `cfb_strength.mcp_server.server.get_champion`,
which this app must not import (it's the MCP/LLM-tool surface, wraps results
in `{"error": ...}` dicts rather than raising, wrong shape for HTTP). Per
issue #3's brief, `_resolve_champion_name` below replicates that same
7-line rank=1 SQL query directly against the connection this app already
holds, then hands the resolved name to `build_team_case` -- the only
non-evidence-layer SQL in this app, by design (issue #4 adds one more:
`api.deps.list_all_team_names`, the grounding check's "known team names"
universe, same justification -- promoted from a private
`api.persona.service._all_team_names` helper by issue #13 so `api.catalog`'s
`/api/teams` route can share it).
"""

from __future__ import annotations

import sqlite3

from cfb_strength.evidence.proof import build_comparison, build_team_case
from fastapi import APIRouter, Depends

from api.deps import get_db_conn, get_narration_cache, get_narrator, list_all_team_names
from api.errors import COMPARISON_ERROR_RESPONSES, TEAM_CASE_ERROR_RESPONSES
from api.models import (
    ChampionRequest,
    ComparisonEnvelope,
    ComparisonRequest,
    ComparisonResultOut,
    TeamCaseEnvelope,
    TeamCaseOut,
    TeamCaseRequest,
)
from api.persona.cache import NarrationCacheStore
from api.persona.claude_client import Narrator
from api.persona.service import narrate_comparison, narrate_team_case

router = APIRouter(prefix="/api/verdict", tags=["verdict"])


def resolve_user_team(conn: sqlite3.Connection, user_team: str | None, sport: str) -> str | None:
    """The only `user_team` a route may hand the persona layer (issue #188).

    `user_team` is interpolated into the Claude system prompt and is part of
    the narration cache key, and since share links (#184) a third party can
    set it. So it is resolved against the sport's team catalog,
    `list_all_team_names(conn, sport)` (the grounding check's own known-name
    universe): surrounding whitespace is stripped, case is ignored, and a
    match comes back in the catalog's canonical spelling, so `"  texas "`
    narrates and caches exactly as `"Texas"`. Anything else becomes `None`:
    empty or whitespace-only text, typos, injection text, another sport's
    team. Aliases (`teams.alternate_names`) are deliberately not matched.

    Unknown is `None`, never a 422: the web client keeps one saved team across
    seasons and sports, so a stale or out-of-scope team must still get a
    verdict, just with no-team narration. For the same reason the lookup is
    scoped to the sport, not the year.

    Matching is unambiguous on the committed data: no two stored names within
    a sport are equal after strip + casefold. If that ever stopped being true,
    the first name in catalog order would win.
    """
    if user_team is None:
        return None
    wanted = user_team.strip().casefold()
    if not wanted:
        return None
    for name in list_all_team_names(conn, sport):
        if name.strip().casefold() == wanted:
            return name
    return None


def _resolve_champion_name(
    conn: sqlite3.Connection, year: int, method: str, sport: str
) -> str | None:
    row = conn.execute(
        """
        SELECT t.school AS school
        FROM ratings r
        JOIN teams t ON t.id = r.team_id
        WHERE r.year = ? AND r.method = ? AND r.rank = 1 AND r.sport = ?
        """,
        (year, method, sport),
    ).fetchone()
    return str(row["school"]) if row is not None else None


@router.post("/champion", response_model=TeamCaseEnvelope, responses=TEAM_CASE_ERROR_RESPONSES)
def champion(
    payload: ChampionRequest,
    conn: sqlite3.Connection = Depends(get_db_conn),
    cache: NarrationCacheStore = Depends(get_narration_cache),
    narrator: Narrator = Depends(get_narrator),
) -> TeamCaseEnvelope:
    """'Who was the best team in <year>?' -- resolve the #1-ranked team, then
    return its full evidentiary case (same shape as /team-case) plus its
    persona narration."""
    name = _resolve_champion_name(conn, payload.year, payload.method, payload.sport)
    # `name is None` (no ratings rows at all for year/method/sport) still
    # needs to surface as UnknownYearError -- build_team_case raises it for
    # us as soon as resolve_team's `_require_year` check runs, whether we
    # pass a real name or any placeholder query string.
    case = build_team_case(
        conn, payload.year, name or "", method=payload.method, sport=payload.sport
    )
    case_out = TeamCaseOut.from_dataclass(case)
    narration = narrate_team_case(
        conn,
        case_out,
        user_team=resolve_user_team(conn, payload.user_team, payload.sport),
        question_type="champion",
        method=payload.method,
        sport=payload.sport,
        cache=cache,
        narrator=narrator,
    )
    return TeamCaseEnvelope(evidence=case_out, narration=narration)


@router.post("/team-case", response_model=TeamCaseEnvelope, responses=TEAM_CASE_ERROR_RESPONSES)
def team_case(
    payload: TeamCaseRequest,
    conn: sqlite3.Connection = Depends(get_db_conn),
    cache: NarrationCacheStore = Depends(get_narration_cache),
    narrator: Narrator = Depends(get_narrator),
) -> TeamCaseEnvelope:
    """'How good was <team> in <year>?'"""
    case = build_team_case(
        conn, payload.year, payload.team, method=payload.method, sport=payload.sport
    )
    case_out = TeamCaseOut.from_dataclass(case)
    narration = narrate_team_case(
        conn,
        case_out,
        user_team=resolve_user_team(conn, payload.user_team, payload.sport),
        question_type="team_case",
        method=payload.method,
        sport=payload.sport,
        cache=cache,
        narrator=narrator,
    )
    return TeamCaseEnvelope(evidence=case_out, narration=narration)


@router.post("/compare", response_model=ComparisonEnvelope, responses=COMPARISON_ERROR_RESPONSES)
def compare(
    payload: ComparisonRequest,
    conn: sqlite3.Connection = Depends(get_db_conn),
    cache: NarrationCacheStore = Depends(get_narration_cache),
    narrator: Narrator = Depends(get_narrator),
) -> ComparisonEnvelope:
    """'Was <team_a> better than <team_b> in <year>?'"""
    comparison = build_comparison(
        conn,
        payload.year,
        payload.team_a,
        payload.team_b,
        method=payload.method,
        sport=payload.sport,
    )
    comparison_out = ComparisonResultOut.from_dataclass(comparison)
    narration = narrate_comparison(
        conn,
        comparison_out,
        user_team=resolve_user_team(conn, payload.user_team, payload.sport),
        method=payload.method,
        sport=payload.sport,
        cache=cache,
        narrator=narrator,
    )
    return ComparisonEnvelope(evidence=comparison_out, narration=narration)
