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

from cfb_strength.contracts import ComparisonResult, OpponentResult, TeamCase
from pydantic import BaseModel, ConfigDict

# ---------------------------------------------------------------------------
# requests
# ---------------------------------------------------------------------------


class ChampionRequest(BaseModel):
    """'Who was the best team in <year>?' -- no team named."""

    model_config = ConfigDict(extra="forbid")

    year: int
    method: str = "keener"
    user_team: str | None = None


class TeamCaseRequest(BaseModel):
    """'How good was <team> in <year>?'"""

    model_config = ConfigDict(extra="forbid")

    year: int
    team: str
    method: str = "keener"
    user_team: str | None = None


class ComparisonRequest(BaseModel):
    """'Was <team_a> better than <team_b> in <year>?'"""

    model_config = ConfigDict(extra="forbid")

    year: int
    team_a: str
    team_b: str
    method: str = "keener"
    user_team: str | None = None


# ---------------------------------------------------------------------------
# responses
# ---------------------------------------------------------------------------


class OpponentResultOut(BaseModel):
    opponent_team_id: int
    opponent_name: str
    opponent_rank: int | None
    opponent_rating: float | None
    result: Literal["W", "L"]
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


class TeamCaseOut(BaseModel):
    year: int
    method: str
    team_id: int
    team_name: str
    rank: int
    rating: float
    wins: int
    losses: int
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
            games=[OpponentResultOut.from_dataclass(g) for g in case.games],
            quality_wins=[OpponentResultOut.from_dataclass(g) for g in case.quality_wins],
            worst_loss=(
                OpponentResultOut.from_dataclass(case.worst_loss)
                if case.worst_loss is not None
                else None
            ),
        )


class ComparisonResultOut(BaseModel):
    year: int
    team_a: dict[str, object]
    team_b: dict[str, object]
    head_to_head: dict[str, object]
    common_opponents: list[dict[str, object]]
    rating_diff: float
    verdict: str

    @classmethod
    def from_dataclass(cls, comparison: ComparisonResult) -> ComparisonResultOut:
        return cls(
            year=comparison.year,
            team_a=comparison.team_a,
            team_b=comparison.team_b,
            head_to_head=comparison.head_to_head,
            common_opponents=comparison.common_opponents,
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


class TeamsOut(BaseModel):
    teams: list[str]


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


class SameTeamComparisonErrorBody(BaseModel):
    error: Literal["same_team_comparison"] = "same_team_comparison"
    team_name: str
