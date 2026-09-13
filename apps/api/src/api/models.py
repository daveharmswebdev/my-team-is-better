"""Request/response Pydantic models for the /api/verdict endpoints.

Response models are structurally faithful to `cfb_strength.contracts`'
`TeamCase` / `ComparisonResult` / `OpponentResult` dataclasses -- same field
names, same shapes, same nesting -- so that issue #4 (the persona layer,
which wraps these same dataclasses in a Claude call) and issue #6 (the web
UI wiring) can both build against this exact JSON shape without guessing.
`*_from_dataclass` constructors below are the one place that mapping is
spelled out, so it can't silently drift from `dataclasses.asdict()`.

Request models intentionally include `user_team` (optional, unused by this
issue's route logic) because Architecture Brief §4.1 already documents the
full request shape as `{question_type, year, team | team_a/team_b,
user_team}` -- carrying the field now means issue #4 doesn't need a request
schema change to add allegiance-aware persona narration later. See this
issue's `contract_gaps` for the routing-shape judgment call this implies.
"""

from __future__ import annotations

from typing import Literal

from cfb_strength.contracts import (
    CommonOpponent,
    ComparisonResult,
    ComparisonTeamSummary,
    Credits,
    DataSourceCredit,
    HeadToHead,
    HeadToHeadMeeting,
    MethodologyCredit,
    OpponentCredit,
    OpponentResult,
    RatingBreakdown,
    TeamCase,
)

# Explicit `X as X` re-exports -- see "shared field types" below.
from cfb_strength.contracts import Method as Method
from cfb_strength.contracts import Sport as Sport
from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# shared field types
# ---------------------------------------------------------------------------
#
# `Method` and `Sport` are the engine's contract aliases, re-exported rather
# than redeclared (issue #112). The redundant `X as X` form is what marks them
# as deliberate re-exports: apps/api runs `mypy --strict`, whose
# `no_implicit_reexport` would otherwise reject `from api.models import Sport`
# in `api.catalog` and elsewhere.
#
# Why these are closed vocabularies at all: `method` and `sport` were once
# bare `str`s, so a typo did not fail, it succeeded emptily.
# `GET /api/years?method=nonsense` (or `?sport=basketball`) answered
# `200 {"years": []}`, which is identical to a real method or league whose
# seasons are not ingested yet, and `/api/years` fills the web year picker.
# `sport` had a second, outbound symptom: `UnknownTeamErrorBody` echoes it
# back, and `apps/web`'s `isVerdictErrorBody` guard rejects the whole body
# when the value is outside its `Sport` union, which collapsed a mapped 404
# into a generic network error (#100). Constraining the request boundary
# fixes both ends, since a value that cannot get in cannot be echoed out.
# A registered-but-uncomputed method (`elo_career` in the test fixture) is
# still a 200 with empty results; that is the state a typo can no longer
# impersonate.
#
# What checks what:
# - packages/cfb-engine's tests/test_contract_vocabularies.py ties both
#   aliases to what the engine runs (`compute_ratings.METHODS`, `ELO_CONFIGS`,
#   the CLI dispatch, argparse's `--sport` choices).
# - tests/test_openapi_vocabularies.py fails if apps/api redeclares either
#   vocabulary, if any `sport`/`method` published in /openapi.json lacks the
#   enum (except the allowlisted `TeamCaseOut.method`, #139) or disagrees with
#   the alias, or if the committed
#   `openapi-vocabularies.json` (what apps/web is checked against) is stale.
# - tests/test_sport_validation.py and tests/test_method_validation.py check
#   at runtime that every alias value is accepted and anything else is a 422.


# ---------------------------------------------------------------------------
# requests
# ---------------------------------------------------------------------------


class ChampionRequest(BaseModel):
    """'Who was the best team in <year>?' -- no team named."""

    model_config = ConfigDict(extra="forbid")

    year: int
    method: Method = "keener"
    user_team: str | None = None
    # Issue #59: threaded through to the evidence-layer calls in
    # `cfb_strength.evidence.proof` (all default to "cfb" themselves, so an
    # existing client that never sends this gets today's exact behavior).
    sport: Sport = "cfb"


class TeamCaseRequest(BaseModel):
    """'How good was <team> in <year>?'"""

    model_config = ConfigDict(extra="forbid")

    year: int
    team: str
    method: Method = "keener"
    user_team: str | None = None
    sport: Sport = "cfb"


class ComparisonRequest(BaseModel):
    """'Was <team_a> better than <team_b> in <year>?'"""

    model_config = ConfigDict(extra="forbid")

    year: int
    team_a: str
    team_b: str
    method: Method = "keener"
    user_team: str | None = None
    sport: Sport = "cfb"


# ---------------------------------------------------------------------------
# responses
# ---------------------------------------------------------------------------


class OpponentResultOut(BaseModel):
    opponent_team_id: int
    opponent_name: str
    opponent_rank: int | None
    opponent_rating: float | None
    # "T" (issue #83): a completed game with equal scores -- see
    # `cfb_strength.contracts.OpponentResult.result`.
    result: Literal["W", "L", "T"]
    team_score: int
    opponent_score: int
    week: int | None
    season_type: str
    neutral_site: bool

    @classmethod
    def from_dataclass(cls, o: OpponentResult) -> OpponentResultOut:
        return cls(
            opponent_team_id=o.opponent_team_id,
            opponent_name=o.opponent_name,
            opponent_rank=o.opponent_rank,
            opponent_rating=o.opponent_rating,
            result=o.result,
            team_score=o.team_score,
            opponent_score=o.opponent_score,
            week=o.week,
            season_type=o.season_type,
            neutral_site=o.neutral_site,
        )


class OpponentCreditOut(BaseModel):
    opponent_team_id: int
    opponent_name: str
    games_played: int
    wins: int
    losses: int
    credit: float
    contribution: float
    explanation: str

    @classmethod
    def from_dataclass(cls, credit: OpponentCredit) -> OpponentCreditOut:
        return cls(
            opponent_team_id=credit.opponent_team_id,
            opponent_name=credit.opponent_name,
            games_played=credit.games_played,
            wins=credit.wins,
            losses=credit.losses,
            credit=credit.credit,
            contribution=credit.contribution,
            explanation=credit.explanation,
        )


class RatingBreakdownOut(BaseModel):
    entries: list[OpponentCreditOut]
    residual_contribution: float

    @classmethod
    def from_dataclass(cls, breakdown: RatingBreakdown) -> RatingBreakdownOut:
        return cls(
            entries=[OpponentCreditOut.from_dataclass(e) for e in breakdown.entries],
            residual_contribution=breakdown.residual_contribution,
        )


class TeamCaseOut(BaseModel):
    year: int
    method: str
    team_id: int
    team_name: str
    rank: int
    rating: float
    wins: int
    losses: int
    # Required, like the dataclass field (issue #83) -- see
    # `cfb_strength.contracts.TeamRating.ties`.
    ties: int
    rating_breakdown: RatingBreakdownOut
    games: list[OpponentResultOut]
    quality_wins: list[OpponentResultOut]
    worst_loss: OpponentResultOut | None

    @classmethod
    def from_dataclass(cls, case: TeamCase) -> TeamCaseOut:
        return cls(
            year=case.year,
            method=case.method,
            team_id=case.team_id,
            team_name=case.team_name,
            rank=case.rank,
            rating=case.rating,
            wins=case.wins,
            losses=case.losses,
            ties=case.ties,
            rating_breakdown=RatingBreakdownOut.from_dataclass(case.rating_breakdown),
            games=[OpponentResultOut.from_dataclass(g) for g in case.games],
            quality_wins=[OpponentResultOut.from_dataclass(g) for g in case.quality_wins],
            worst_loss=(
                OpponentResultOut.from_dataclass(case.worst_loss)
                if case.worst_loss is not None
                else None
            ),
        )


class ComparisonTeamSummaryOut(BaseModel):
    team_id: int
    team_name: str
    rank: int
    rating: float
    wins: int
    losses: int
    ties: int
    rating_breakdown: RatingBreakdownOut
    quality_wins: list[OpponentResultOut]
    worst_loss: OpponentResultOut | None

    @classmethod
    def from_dataclass(cls, summary: ComparisonTeamSummary) -> ComparisonTeamSummaryOut:
        return cls(
            team_id=summary.team_id,
            team_name=summary.team_name,
            rank=summary.rank,
            rating=summary.rating,
            wins=summary.wins,
            losses=summary.losses,
            ties=summary.ties,
            rating_breakdown=RatingBreakdownOut.from_dataclass(summary.rating_breakdown),
            quality_wins=[OpponentResultOut.from_dataclass(g) for g in summary.quality_wins],
            worst_loss=(
                OpponentResultOut.from_dataclass(summary.worst_loss)
                if summary.worst_loss is not None
                else None
            ),
        )


class HeadToHeadMeetingOut(BaseModel):
    week: int | None
    season_type: str
    neutral_site: bool
    home_team: str
    away_team: str
    home_points: int
    away_points: int
    winner: str | None

    @classmethod
    def from_dataclass(cls, meeting: HeadToHeadMeeting) -> HeadToHeadMeetingOut:
        return cls(
            week=meeting.week,
            season_type=meeting.season_type,
            neutral_site=meeting.neutral_site,
            home_team=meeting.home_team,
            away_team=meeting.away_team,
            home_points=meeting.home_points,
            away_points=meeting.away_points,
            winner=meeting.winner,
        )


class HeadToHeadOut(BaseModel):
    played: bool
    meetings: list[HeadToHeadMeetingOut]

    @classmethod
    def from_dataclass(cls, head_to_head: HeadToHead) -> HeadToHeadOut:
        return cls(
            played=head_to_head.played,
            meetings=[HeadToHeadMeetingOut.from_dataclass(m) for m in head_to_head.meetings],
        )


class CommonOpponentOut(BaseModel):
    opponent_team_id: int
    opponent_name: str
    opponent_rank: int | None
    team_a_result: Literal["W", "L", "T"]
    team_a_score: int
    team_a_opponent_score: int
    team_b_result: Literal["W", "L", "T"]
    team_b_score: int
    team_b_opponent_score: int

    @classmethod
    def from_dataclass(cls, common_opponent: CommonOpponent) -> CommonOpponentOut:
        return cls(
            opponent_team_id=common_opponent.opponent_team_id,
            opponent_name=common_opponent.opponent_name,
            opponent_rank=common_opponent.opponent_rank,
            team_a_result=common_opponent.team_a_result,
            team_a_score=common_opponent.team_a_score,
            team_a_opponent_score=common_opponent.team_a_opponent_score,
            team_b_result=common_opponent.team_b_result,
            team_b_score=common_opponent.team_b_score,
            team_b_opponent_score=common_opponent.team_b_opponent_score,
        )


class ComparisonResultOut(BaseModel):
    year: int
    team_a: ComparisonTeamSummaryOut
    team_b: ComparisonTeamSummaryOut
    head_to_head: HeadToHeadOut
    common_opponents: list[CommonOpponentOut]
    rating_diff: float
    verdict: str

    @classmethod
    def from_dataclass(cls, comparison: ComparisonResult) -> ComparisonResultOut:
        return cls(
            year=comparison.year,
            team_a=ComparisonTeamSummaryOut.from_dataclass(comparison.team_a),
            team_b=ComparisonTeamSummaryOut.from_dataclass(comparison.team_b),
            head_to_head=HeadToHeadOut.from_dataclass(comparison.head_to_head),
            common_opponents=[
                CommonOpponentOut.from_dataclass(c) for c in comparison.common_opponents
            ],
            rating_diff=comparison.rating_diff,
            verdict=comparison.verdict,
        )


# ---------------------------------------------------------------------------
# catalog responses (issue #13) -- plain evidence-catalog reads for the
# `apps/web` year/team picker fields. No persona/narration envelope: these
# aren't verdicts, just the universe of valid inputs.
# ---------------------------------------------------------------------------


class YearsOut(BaseModel):
    years: list[int]


class TeamDetailOut(BaseModel):
    """One selectable team's display/search metadata (issue #78, epic #76),
    faithful to `api.deps.TeamRecord`.

    `name` is `teams.school` verbatim and is the value a client submits
    back -- the verdict lookup, the persona grounding check, the golden
    dataset, and every cached narration key are all keyed on that exact
    string, so it must never be display-joined with the mascot. `mascot` is
    null for every NFL row (whose `school` already carries city *and*
    nickname) and for any CFB team CFBD has no mascot for; `aliases` is the
    decoded `teams.alternate_names` array, `[]` when there are none.
    """

    name: str
    mascot: str | None = None
    aliases: list[str] = Field(default_factory=list)


class TeamsOut(BaseModel):
    """`teams` is the canonical submitted-value list; `team_details` is a
    parallel array carrying the same names in the same order plus issue
    #78's display metadata.

    The parallel-array shape is deliberate rather than changing `teams`'
    element type to an object: `apps/web`'s consumer lands in a separate PR
    and a separate production deploy, and its `TeamsOut` type declares
    `teams: string[]` and renders `value={name}` straight from it -- so
    changing the element type would render `[object Object]` in the live
    team picker for the whole window between the two merges. Both arrays
    come from one query (`api.deps.list_team_records`), so a consumer may
    zip them by index.
    """

    teams: list[str]
    team_details: list[TeamDetailOut] = Field(default_factory=list)


class MethodologyCreditOut(BaseModel):
    name: str
    citation: str
    url: str
    summary: str

    @classmethod
    def from_dataclass(cls, methodology: MethodologyCredit) -> MethodologyCreditOut:
        return cls(
            name=methodology.name,
            citation=methodology.citation,
            url=methodology.url,
            summary=methodology.summary,
        )


class DataSourceCreditOut(BaseModel):
    name: str
    url: str
    note: str

    @classmethod
    def from_dataclass(cls, data_source: DataSourceCredit) -> DataSourceCreditOut:
        return cls(
            name=data_source.name,
            url=data_source.url,
            note=data_source.note,
        )


class CreditsOut(BaseModel):
    """The About page's attribution payload, faithful to
    `cfb_strength.contracts.Credits`.

    `methodologies` is a list (it was a single `methodology` object until
    the Elo engine landed) because the engine now implements more than one
    rating method and PRD §5.6 credits the whole basis of the rankings, not
    whichever method answered the current question. Order is `get_credits()`'s
    order -- Keener's method, then Elo -- and is preserved here rather than
    sorted, so the About page renders the default method first.
    """

    methodologies: list[MethodologyCreditOut]
    data_sources: list[DataSourceCreditOut]

    @classmethod
    def from_dataclass(cls, credits: Credits) -> CreditsOut:
        return cls(
            methodologies=[
                MethodologyCreditOut.from_dataclass(methodology)
                for methodology in credits.methodologies
            ],
            data_sources=[
                DataSourceCreditOut.from_dataclass(data_source)
                for data_source in credits.data_sources
            ],
        )


# ---------------------------------------------------------------------------
# persona narration envelope (issue #4) -- wraps issue #3's evidence rather
# than replacing it, so issue #6 (the web UI) can render `narration.text`
# next to the evidence "receipts" from the same response.
# ---------------------------------------------------------------------------


class NarrationOut(BaseModel):
    text: str
    contested: bool
    cached: bool


class TeamCaseEnvelope(BaseModel):
    evidence: TeamCaseOut
    narration: NarrationOut


class ComparisonEnvelope(BaseModel):
    evidence: ComparisonResultOut
    narration: NarrationOut


# ---------------------------------------------------------------------------
# error bodies (Architecture Brief §4.4 -- HTTP-response half only, no
# persona copy here, that's issue #4's job)
# ---------------------------------------------------------------------------


class UnknownYearErrorBody(BaseModel):
    error: Literal["unknown_year"] = "unknown_year"
    year: int
    available_years: list[int]


class AmbiguousTeamErrorBody(BaseModel):
    error: Literal["ambiguous_team"] = "ambiguous_team"
    query: str
    candidates: list[str]


class UnknownTeamErrorBody(BaseModel):
    """The zero-match case (issue #100) -- the opposite problem from
    `AmbiguousTeamErrorBody`, which is >1 match and whose `candidates` is
    always non-empty.

    **Deliberately carries no suggestion list.** The first cut of #100 added
    one and it could not work: the engine's `resolve_team` already resolves
    anything scoring >= 0.6, so this branch is reached only when *nothing*
    does, and no cutoff separates signal from noise in what is left
    ("Gonzaga"/"Georgia" scores 0.5714 and outranks "Texas"/"Houston
    Texans" at 0.5263). Real typos never arrive here at all --
    "Alabma"/"Alabama" scores 0.9231 and resolves upstream. The field
    shipped nonsense: "Abilene Christian" came back suggesting Michigan,
    Minnesota, Ole Miss and Virginia. See `contracts.UnknownTeamError` for
    the full measurement.

    Clients render a plain not-found state ("no rating for that team in that
    season and league"), which still clears #100's dead end -- the bug #100
    fixed was a 422 `ambiguous_team` "did you mean:" prompt with an *empty*
    pick list under it, and an honest not-found is not that.

    `sport` is the `Sport` literal, not a bare `str`, because `apps/web`'s
    `isVerdictErrorBody` guard rejects this entire body if the value falls
    outside its own `Sport` union -- which would collapse this mapped 404
    back into a generic network error.
    """

    error: Literal["unknown_team"] = "unknown_team"
    query: str
    year: int
    sport: Sport


class SameTeamComparisonErrorBody(BaseModel):
    error: Literal["same_team_comparison"] = "same_team_comparison"
    team_name: str


# ---------------------------------------------------------------------------
# `{"detail": <Body>}` envelopes (issue #111) -- the error bodies as they
# actually go over the wire. `api.errors`' handlers send
# `{"detail": body.model_dump()}`, so the bare `*ErrorBody` models above are
# NOT a response's schema. These are what `/openapi.json` declares, via
# `api.errors.ENGINE_ERROR_RESPONSES`. tests/test_openapi_error_responses.py
# validates real responses against the published schema, so declaring a bare
# body in their place fails CI.
# ---------------------------------------------------------------------------


class UnknownYearErrorResponse(BaseModel):
    detail: UnknownYearErrorBody


class AmbiguousTeamErrorResponse(BaseModel):
    detail: AmbiguousTeamErrorBody


class UnknownTeamErrorResponse(BaseModel):
    detail: UnknownTeamErrorBody


class SameTeamComparisonErrorResponse(BaseModel):
    detail: SameTeamComparisonErrorBody
