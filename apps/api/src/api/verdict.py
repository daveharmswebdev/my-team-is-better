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
`build_comparison`); /champion has its own set, because it adds the one
API-local error, `MissingChampionError` (#172, see
`_resolve_champion_name`). For every route in the app,
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
`api.repositories.teams.list_all_team_names`, the grounding check's "known
team names" universe, same justification -- promoted from a private
`api.persona.service._all_team_names` helper by issue #13 so `api.catalog`'s
`/api/teams` route can share it, and moved out of `api.deps` by issue #209).

Since issue #245 the persona layer no longer runs that query itself. Each
route reads the sport's catalog exactly once, `list_team_records(conn,
sport)`, and uses it twice: the records canonicalise `user_team`
(`resolve_user_team`), and the names derived from them (`catalog_names`) are
the grounding universe, handed to `narrate_team_case`/`narrate_comparison`
as `known_team_names`. Before #245 a request with a `user_team` read the
catalog twice on a cache miss -- the records here and `list_all_team_names`
in `api.persona.service` -- for the same universe of names.
`tests/test_verdict_catalog_reads.py` counts the reads on the request's own
connection and pins the two queries' equivalence on both sports' fixtures.
"""

from __future__ import annotations

import sqlite3
import unicodedata
from collections.abc import Sequence

from cfb_strength.contracts import UnknownYearError
from cfb_strength.evidence.proof import build_comparison, build_team_case, list_available_years
from fastapi import APIRouter, Depends

from api.deps import get_db_conn, get_narration_cache, get_narrator
from api.errors import (
    CHAMPION_ERROR_RESPONSES,
    COMPARISON_ERROR_RESPONSES,
    TEAM_CASE_ERROR_RESPONSES,
    MissingChampionError,
)
from api.models import (
    MAX_SEASON_YEAR,
    MIN_SEASON_YEAR,
    USER_TEAM_MAX_LENGTH,
    ChampionRequest,
    ComparisonEnvelope,
    ComparisonRequest,
    ComparisonResultOut,
    Method,
    Sport,
    TeamCaseEnvelope,
    TeamCaseOut,
    TeamCaseRequest,
)
from api.persona.cache import NarrationCacheStore
from api.persona.claude_client import Narrator
from api.persona.service import narrate_comparison, narrate_team_case
from api.repositories.teams import TeamRecord, list_team_records

router = APIRouter(prefix="/api/verdict", tags=["verdict"])


def _fold(text: str) -> str:
    """Accent- and case-insensitive form of `text`.

    Mirrors `fold` in `apps/web/src/components/TeamCombobox/teamMatching.ts`
    (`normalize('NFD')`, strip `\\p{Diacritic}`, `toLowerCase()`): decompose,
    drop combining marks, casefold. On every committed db the two agree; the
    only non-ASCII names are 'San José State' and its alias 'San José St'.
    """
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()


def resolve_user_team(records: Sequence[TeamRecord], user_team: str | None) -> str | None:
    """The only `user_team` a route may hand the persona layer (issue #188).

    `user_team` is interpolated into the Claude system prompt and is part of
    the narration cache key, and since share links (#184) a third party can
    set it. So it is resolved against the sport's team catalog, `records`
    -- `list_team_records(conn, sport)` with no year, the same universe as
    the grounding check's known team names, plus aliases -- and only a
    canonical catalog name, `teams.school` verbatim, ever comes back. The
    route reads the catalog and passes it in (issue #245), so this never
    queries; the sport scoping is the caller's read.

    The matching rule mirrors the web's `isTeamInCatalog`
    (`apps/web/src/components/TeamCombobox/teamMatching.ts`), so a value the
    web's 'Your team' field treats as a real team is narrated as that team:

    1. Strip surrounding whitespace. Empty, or longer than
       `USER_TEAM_MAX_LENGTH`, is `None`. The web field and its saved value
       have no length bound, so this is a cutoff, not a request error.
    2. Fold both sides (`_fold`: accents dropped, case ignored) and look for
       an exact match on a canonical name. `"  san jose state "` becomes
       `"San José State"`.
    3. Failing that, an exact folded match on an alias
       (`teams.alternate_names`) counts only when exactly one team has it:
       `"OSU"` becomes `"Ohio State"`, while `"LAM"` (Lamar's and
       Lambuth's) is `None`. The web only asks "is this some team?", so it
       has no ambiguity rule to mirror; picking a team at random would put
       the wrong allegiance in the prompt.

    A canonical name beats another team's identical alias. No substring,
    prefix, mascot or fuzzy matching.

    Unknown is `None`, never a 422: the web client keeps one saved team across
    seasons and sports, so a stale or out-of-scope team must still get a
    verdict, just with no-team narration. For the same reason the catalog the
    routes read is scoped to the sport, not the year.

    No two canonical names within a sport fold equal on the committed data.
    If that ever stopped being true, the first name in catalog order would win.
    """
    if user_team is None:
        return None
    stripped = user_team.strip()
    if not stripped or len(stripped) > USER_TEAM_MAX_LENGTH:
        return None
    wanted = _fold(stripped)

    for record in records:
        if _fold(record.name) == wanted:
            return record.name

    alias_owners = {
        record.name for record in records if any(_fold(alias) == wanted for alias in record.aliases)
    }
    if len(alias_owners) != 1:
        return None
    return next(iter(alias_owners))


def catalog_names(records: Sequence[TeamRecord]) -> list[str]:
    """The grounding check's "known team names" universe, derived from the
    catalog a route already read (issue #245): every canonical name for the
    sport, in catalog order. Equal as a set to `list_all_team_names(conn,
    sport)` -- `list_team_records` without a `year` is that same
    `DISTINCT school` list with two more columns, and
    `tests/test_verdict_catalog_reads.py` pins the equality on both sports'
    fixtures -- so the persona layer no longer needs a connection to build it.
    """
    return [record.name for record in records]


def require_season_year(conn: sqlite3.Connection, year: int, method: str, sport: Sport) -> None:
    """Reject a `year` outside `MIN_SEASON_YEAR..MAX_SEASON_YEAR` before any
    SQL binds it (issue #189).

    Every verdict route calls this first. Without it a year too large for a
    SQLite INTEGER (`100000000000000000000`) reached `conn.execute` in
    `_resolve_champion_name` and raised `OverflowError`, which no handler in
    `api.errors` maps, so /champion answered 500. The other two routes never
    bound the year -- the engine's `_require_year` compares in Python first
    -- but they call this too, so the bound is one rule checked in one place
    rather than an accident of which query runs first.

    Raises `UnknownYearError` built exactly as the engine's `_require_year`
    builds it: the year as sent, plus the real `available_years` for the
    request's method and sport. That is the same 404 the web already renders
    for a rated-but-absent year; no new error code (see `MIN_SEASON_YEAR` in
    `api.models` for why this is not a request-validation 422).
    """
    if MIN_SEASON_YEAR <= year <= MAX_SEASON_YEAR:
        return
    raise UnknownYearError(year, list_available_years(conn, method, sport))


def _resolve_champion_name(
    conn: sqlite3.Connection, year: int, method: Method, sport: Sport
) -> str:
    """The `teams.school` of the rank-1 row for `year`/`method`/`sport`.

    No such row means one of two things, and they are told apart the way
    the engine's `_require_year` would (issue #172):

    * the year has no ratings at all for that method and sport --
      `UnknownYearError`, built exactly as the engine builds it, so the
      client sees the same `unknown_year` 404 it always has;
    * the year IS rated but nothing in it is ranked first --
      `MissingChampionError`, a data-integrity fault mapped to 500. Before
      #172 this case returned `None`, the caller fell through to
      `build_team_case(conn, year, "")`, and the empty query came back as a
      422 `ambiguous_team` naming every rated team as a candidate.
    """
    row = conn.execute(
        """
        SELECT t.school AS school
        FROM ratings r
        JOIN teams t ON t.id = r.team_id
        WHERE r.year = ? AND r.method = ? AND r.rank = 1 AND r.sport = ?
        """,
        (year, method, sport),
    ).fetchone()
    if row is not None:
        return str(row["school"])
    available_years = list_available_years(conn, method, sport)
    if year not in available_years:
        raise UnknownYearError(year, available_years)
    raise MissingChampionError(year, method, sport)


@router.post("/champion", response_model=TeamCaseEnvelope, responses=CHAMPION_ERROR_RESPONSES)
def champion(
    payload: ChampionRequest,
    conn: sqlite3.Connection = Depends(get_db_conn),
    cache: NarrationCacheStore = Depends(get_narration_cache),
    narrator: Narrator = Depends(get_narrator),
) -> TeamCaseEnvelope:
    """'Who was the best team in <year>?' -- resolve the #1-ranked team, then
    return its full evidentiary case (same shape as /team-case) plus its
    persona narration."""
    require_season_year(conn, payload.year, payload.method, payload.sport)
    name = _resolve_champion_name(conn, payload.year, payload.method, payload.sport)
    case = build_team_case(conn, payload.year, name, method=payload.method, sport=payload.sport)
    case_out = TeamCaseOut.from_dataclass(case)
    catalog = list_team_records(conn, payload.sport)
    narration = narrate_team_case(
        case_out,
        user_team=resolve_user_team(catalog, payload.user_team),
        question_type="champion",
        method=payload.method,
        sport=payload.sport,
        known_team_names=catalog_names(catalog),
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
    require_season_year(conn, payload.year, payload.method, payload.sport)
    case = build_team_case(
        conn, payload.year, payload.team, method=payload.method, sport=payload.sport
    )
    case_out = TeamCaseOut.from_dataclass(case)
    catalog = list_team_records(conn, payload.sport)
    narration = narrate_team_case(
        case_out,
        user_team=resolve_user_team(catalog, payload.user_team),
        question_type="team_case",
        method=payload.method,
        sport=payload.sport,
        known_team_names=catalog_names(catalog),
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
    require_season_year(conn, payload.year, payload.method, payload.sport)
    comparison = build_comparison(
        conn,
        payload.year,
        payload.team_a,
        payload.team_b,
        method=payload.method,
        sport=payload.sport,
    )
    comparison_out = ComparisonResultOut.from_dataclass(comparison)
    catalog = list_team_records(conn, payload.sport)
    narration = narrate_comparison(
        comparison_out,
        user_team=resolve_user_team(catalog, payload.user_team),
        method=payload.method,
        sport=payload.sport,
        known_team_names=catalog_names(catalog),
        cache=cache,
        narrator=narrator,
    )
    return ComparisonEnvelope(evidence=comparison_out, narration=narration)
