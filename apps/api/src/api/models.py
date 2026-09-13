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
from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# shared field types
# ---------------------------------------------------------------------------


Method = Literal["keener", "elo", "elo_career"]
"""The rating methods the engine actually implements.

`method` used to be a bare `str` here and on `api.catalog`'s query params,
which meant a typo did not fail -- it succeeded and returned nothing.
`GET /api/years?method=nonsense` answered `200 {"years": []}`, identical to
the answer for a real method whose seasons are not ingested yet, and
`/api/years` is what fills the web year picker. A misspelling was therefore
indistinguishable from missing data, for the user and for us.

Deliberately a hand-written literal rather than one derived from
`cfb_strength.ratings.compute_ratings.METHODS`: `apps/api` may not import
`cfb_strength.ratings` at all (docs/ARCHITECTURE.md §2's layering rule --
this app may import `cfb_strength.evidence`, `cfb_strength.db`,
`cfb_strength.contracts` and `cfb_strength.config`, and nothing else from
the engine; `apps/api/.importlinter` checks it, issue #54). The duplication
is the price of the boundary; `tests/test_method_validation.py` is what
catches it drifting when a method is added or removed.

`elo_career` is admitted here regardless of whether anything has been
computed under it in a given database -- it is a registered method, and
"registered but not computed" must stay a 200 with empty results, since that
is exactly the state a typo may no longer impersonate.
"""


Sport = Literal["cfb", "nfl"]
"""The leagues the engine actually has rated data for.

Constrained for the same reason as `Method` above, with a second symptom on
top. Inbound, `sport` was a bare `str`, so `GET /api/years?sport=basketball`
answered `200 {"years": []}` -- indistinguishable from a real league whose
seasons are not ingested yet. Outbound, `UnknownTeamErrorBody` echoes the
requested `sport` straight back, and `apps/web` types that field as a
`Sport` union whose `isVerdictErrorBody` guard rejects the **whole body**
when the value is outside it: an unrecognised sport turned a mapped 404 into
a generic network error, reintroducing the dead end issue #100 removed.
Constraining the request boundary fixes both ends at once -- a value that
cannot get in cannot be echoed back out.

Hand-written for a narrower reason than `Method` above: the engine simply
exposes no shared sport alias to import. It inlines the same
`Literal["cfb", "nfl"]` on `GameRow.sport`/`TeamRow.sport` in
`cfb_strength.contracts`, which this app *is* permitted to import (and does,
just below) under docs/ARCHITECTURE.md §2's layering rule. Defining that
alias is an engine-side change, not one `apps/api` may make. The duplication
is the price until then, and it is only half-checked (see #112): since #102,
mypy fails if this literal admits a league the engine's `resolve_team` /
`build_team_case` / `build_comparison` signatures don't, but nothing yet
fails if the *engine* gains a league this literal lacks.
`tests/test_sport_validation.py` pins the request boundary to these two
values; it does not detect that engine-ahead drift either.
"""


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
    team_a_result: Literal["W", "L"]
    team_a_score: int
    team_a_opponent_score: int
    team_b_result: Literal["W", "L"]
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
