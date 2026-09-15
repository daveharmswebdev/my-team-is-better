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
    CommonOpponentMeeting,
    ComparisonResult,
    ComparisonTeamSummary,
    Credits,
    DataSourceCredit,
    EloGameStep,
    EloLedger,
    HeadToHead,
    HeadToHeadMeeting,
    MethodologyCredit,
    OpponentCredit,
    OpponentResult,
    PlayerCareer,
    PlayerCareerTotals,
    PlayerComparison,
    PlayerHeadToHead,
    PlayerHeadToHeadGame,
    PlayerLeaderCategory,
    PlayerLeaderRow,
    PlayerLeaders,
    PlayerLeaderSort,
    PlayerSearch,
    PlayerSearchRow,
    PlayerSeasonLine,
    PlayerSeasonType,
    PlayerStats,
    RatingBreakdown,
    StarterRecord,
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

# Issue #188: `user_team` is interpolated into the persona system prompt, and
# since share links (#184) a third party can set it. The request models accept
# any string for it on purpose: the web's 'Your team' field and its saved value
# have no length bound, so a 422 here would break every verdict for a user with
# a long saved value. Instead `api.verdict.resolve_user_team` resolves the value
# against the team catalog, so only a canonical team name ever reaches the
# prompt or the cache key, and treats anything longer than this (after
# stripping) as no team. 64 matches `apps/web`'s share-link bound
# (`MAX_TEAM_NAME_LENGTH` in `HomePage/shareLink.ts`) and is more than double
# the longest stored team name or alias (27 chars).
USER_TEAM_MAX_LENGTH = 64

# Issue #189: a season year has exactly four digits (1000..9999 inclusive) --
# the same shape the web's share-link parser (#184, `HomePage/shareLink.ts`)
# accepts. The bounds are derived from the digit count so the rule is named
# once, the way the parser states it. `year` stays a plain `int` on the
# request models rather than a `Field(ge=, le=)`: an out-of-range year is
# the existing `unknown_year` 404 (which the web already renders with its
# `available_years`), not a request-validation 422, and the 404 body echoes
# the year as sent -- including one too large for a SQLite INTEGER, which
# used to reach sqlite3 and raise an unmapped `OverflowError`.
# `api.verdict.require_season_year` is the one place the bound is checked.
SEASON_YEAR_DIGITS = 4
MIN_SEASON_YEAR = 10 ** (SEASON_YEAR_DIGITS - 1)
MAX_SEASON_YEAR = 10**SEASON_YEAR_DIGITS - 1


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
    # `games.id` (issue #218) -- see `cfb_strength.contracts.OpponentResult.game_id`.
    game_id: int
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
            game_id=o.game_id,
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


class EloGameStepOut(BaseModel):
    """One game's Elo update, from one team's side (issue #183), faithful to
    `cfb_strength.contracts.EloGameStep` -- see its docstring for the
    identities every step satisfies.

    Every field is copied as the engine stored it, never recomputed. Field
    order here is the published JSON order `apps/web` builds against (game
    identity, then the matchup, then the arithmetic in the order it runs);
    it differs from the dataclass's, whose defaulted fields must come last.
    """

    game_number: int
    week: int | None
    season_type: str
    start_date: str | None
    opponent_team_id: int
    opponent_name: str
    venue: Literal["home", "away", "neutral"]
    team_points: int
    opponent_points: int
    result: Literal["W", "L", "T"]
    rating_before: float
    opponent_rating_before: float
    home_field_adjustment: float
    rating_gap: float
    win_expectancy: float
    mov_multiplier: float
    shift: float
    rating_after: float

    @classmethod
    def from_dataclass(cls, step: EloGameStep) -> EloGameStepOut:
        return cls(
            game_number=step.game_number,
            week=step.week,
            season_type=step.season_type,
            start_date=step.start_date,
            opponent_team_id=step.opponent_team_id,
            opponent_name=step.opponent_name,
            venue=step.venue,
            team_points=step.team_points,
            opponent_points=step.opponent_points,
            result=step.result,
            rating_before=step.rating_before,
            opponent_rating_before=step.opponent_rating_before,
            home_field_adjustment=step.home_field_adjustment,
            rating_gap=step.rating_gap,
            win_expectancy=step.win_expectancy,
            mov_multiplier=step.mov_multiplier,
            shift=step.shift,
            rating_after=step.rating_after,
        )


class EloLedgerOut(BaseModel):
    """The shown work behind a season Elo rating (issue #183), faithful to
    `cfb_strength.contracts.EloLedger`: the constants the walk ran with and
    every game's update in order. `steps[-1].rating_after` is the rating.

    Published to clients, but deliberately kept out of the persona fact
    block (`api.persona.service`): narrating ledger figures is an open
    question (#175), not something this field quietly opts the narrator
    into.

    `mov_denom_floor_fraction` (issue #194) is the margin-of-victory
    denominator floor as a fraction of `mov_scale`, copied from the ledger
    as the engine read it back from `elo_ledger_configs`. It is required
    with no default on purpose: the value is whatever the walk actually
    used, and a stored fraction other than the engine's constant must reach
    the client as stored, never be masked by a hard-coded "half" here.
    """

    starting_rating: float
    k: float
    hfa: float
    scale: float
    mov_scale: float
    mov_autocorr: float
    mov_denom_floor_fraction: float
    steps: list[EloGameStepOut]

    @classmethod
    def from_dataclass(cls, ledger: EloLedger) -> EloLedgerOut:
        return cls(
            starting_rating=ledger.starting_rating,
            k=ledger.k,
            hfa=ledger.hfa,
            scale=ledger.scale,
            mov_scale=ledger.mov_scale,
            mov_autocorr=ledger.mov_autocorr,
            mov_denom_floor_fraction=ledger.mov_denom_floor_fraction,
            steps=[EloGameStepOut.from_dataclass(s) for s in ledger.steps],
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
    # Issue #183: null for keener and elo_career, which record no ledger.
    elo_ledger: EloLedgerOut | None
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
            elo_ledger=(
                EloLedgerOut.from_dataclass(case.elo_ledger)
                if case.elo_ledger is not None
                else None
            ),
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
    # Issue #183: this team's own ledger; null for keener and elo_career.
    elo_ledger: EloLedgerOut | None
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
            elo_ledger=(
                EloLedgerOut.from_dataclass(summary.elo_ledger)
                if summary.elo_ledger is not None
                else None
            ),
            quality_wins=[OpponentResultOut.from_dataclass(g) for g in summary.quality_wins],
            worst_loss=(
                OpponentResultOut.from_dataclass(summary.worst_loss)
                if summary.worst_loss is not None
                else None
            ),
        )


class HeadToHeadMeetingOut(BaseModel):
    # `games.id` (issue #218) -- see `cfb_strength.contracts.OpponentResult.game_id`.
    game_id: int
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
            game_id=meeting.game_id,
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


class CommonOpponentMeetingOut(BaseModel):
    """One game a compared side played against a shared opponent (issue
    #130), faithful to `cfb_strength.contracts.CommonOpponentMeeting`.

    Team-relative, like `OpponentResultOut`: `result` and the score pair are
    from that side's perspective, so `team_score` is always the compared
    team's own points -- the order the persona grounding check accepts.
    """

    # `games.id` (issue #218) -- see `cfb_strength.contracts.OpponentResult.game_id`.
    game_id: int
    result: Literal["W", "L", "T"]
    team_score: int
    opponent_score: int
    week: int | None
    season_type: str

    @classmethod
    def from_dataclass(cls, meeting: CommonOpponentMeeting) -> CommonOpponentMeetingOut:
        return cls(
            game_id=meeting.game_id,
            result=meeting.result,
            team_score=meeting.team_score,
            opponent_score=meeting.opponent_score,
            week=meeting.week,
            season_type=meeting.season_type,
        )


class CommonOpponentOut(BaseModel):
    """A team both compared sides played, with EVERY meeting per side (issue
    #130), faithful to `cfb_strength.contracts.CommonOpponent`.

    Each list is non-empty and chronological (regular season by week, then
    postseason), copied in the engine's order: never reordered or deduped.
    No per-side W-L-T aggregate -- derivable from the list, and one more
    thing that could disagree with it (founder decision on #130).
    """

    opponent_team_id: int
    opponent_name: str
    opponent_rank: int | None
    team_a_meetings: list[CommonOpponentMeetingOut]
    team_b_meetings: list[CommonOpponentMeetingOut]

    @classmethod
    def from_dataclass(cls, common_opponent: CommonOpponent) -> CommonOpponentOut:
        return cls(
            opponent_team_id=common_opponent.opponent_team_id,
            opponent_name=common_opponent.opponent_name,
            opponent_rank=common_opponent.opponent_rank,
            team_a_meetings=[
                CommonOpponentMeetingOut.from_dataclass(m) for m in common_opponent.team_a_meetings
            ],
            team_b_meetings=[
                CommonOpponentMeetingOut.from_dataclass(m) for m in common_opponent.team_b_meetings
            ],
        )


class ComparisonResultOut(BaseModel):
    year: int
    # Issue #152: the method both teams' ranks/ratings/rating_diff come from.
    # The engine field is already `Method`, so this publishes a real enum.
    method: Method
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
            method=comparison.method,
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
    faithful to `api.repositories.teams.TeamRecord`.

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
    come from one query (`api.repositories.teams.list_team_records`), so a consumer may
    zip them by index.
    """

    teams: list[str]
    team_details: list[TeamDetailOut] = Field(default_factory=list)


class MethodologyCreditOut(BaseModel):
    name: str
    citation: str
    url: str
    summary: str
    # Issue #144: the registered rating methods this citation covers, in the
    # engine's order, so `methods[0]` is the credit's stable id downstream.
    # Typed with the contract's `Method` alias (not `str`) so /openapi.json
    # publishes the enum and apps/web gets `Method[]`, and required with no
    # default so a credit can never be published covering nothing.
    methods: list[Method]

    @classmethod
    def from_dataclass(cls, methodology: MethodologyCredit) -> MethodologyCreditOut:
        return cls(
            name=methodology.name,
            citation=methodology.citation,
            url=methodology.url,
            summary=methodology.summary,
            # The engine holds a tuple (frozen dataclass); JSON has no tuple,
            # so it goes out as an array in the same order.
            methods=list(methodology.methods),
        )


class DataSourceCreditOut(BaseModel):
    # Issue #296: the source's stable id ("cfbd", "nflverse_games",
    # "nflverse_player_stats"), copied from `DataSourceCredit.id`, so a page
    # showing one source's data picks its credit without keying on `name`.
    id: str
    name: str
    url: str
    note: str

    @classmethod
    def from_dataclass(cls, data_source: DataSourceCredit) -> DataSourceCreditOut:
        return cls(
            id=data_source.id,
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

    Each methodology carries `methods` (issue #144): the registered rating
    methods that citation covers, copied from the engine's
    `MethodologyCredit.methods`. The About page keys its article anchors on
    `methods[0]` (`keener`, `elo`) instead of on a display name that could
    be reworded, and the engine's tests/test_evidence_credits.py guarantees
    every registered method is covered by exactly one credit, so the web
    side can map any `method` value to exactly one article without a
    lookup table of its own.
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
# player read layer (issue #296) -- `cfb_strength.players`' leaders and career
# dataclasses, published by `api.players`. Faithful field for field: same
# names, same nesting, rows and season lines in the engine's order. The one
# addition is `StarterRecordOut.starts`, the dataclass's own property
# (wins + losses + ties), so apps/web never re-derives it. Every stat is
# `int | None` and required: None means the source did not record it and
# must reach the client as `null`, never 0 and never an omitted key.
# ---------------------------------------------------------------------------


class StarterRecordOut(BaseModel):
    wins: int
    losses: int
    ties: int
    starts: int

    @classmethod
    def from_dataclass(cls, record: StarterRecord) -> StarterRecordOut:
        return cls(
            wins=record.wins,
            losses=record.losses,
            ties=record.ties,
            starts=record.starts,
        )


class PlayerStatsOut(BaseModel):
    completions: int | None
    attempts: int | None
    passing_yards: int | None
    passing_tds: int | None
    passing_interceptions: int | None
    sacks_suffered: int | None
    sack_yards_lost: int | None
    carries: int | None
    rushing_yards: int | None
    rushing_tds: int | None

    @classmethod
    def from_dataclass(cls, stats: PlayerStats) -> PlayerStatsOut:
        return cls(
            completions=stats.completions,
            attempts=stats.attempts,
            passing_yards=stats.passing_yards,
            passing_tds=stats.passing_tds,
            passing_interceptions=stats.passing_interceptions,
            sacks_suffered=stats.sacks_suffered,
            sack_yards_lost=stats.sack_yards_lost,
            carries=stats.carries,
            rushing_yards=stats.rushing_yards,
            rushing_tds=stats.rushing_tds,
        )


class PlayerLeaderRowOut(BaseModel):
    # The engine's competition rank over the whole qualifying population;
    # null when the sort value is null (those rows come last).
    rank: int | None
    player_id: int
    display_name: str
    position: str | None
    first_season: int
    last_season: int
    games: int | None
    record: StarterRecordOut
    stats: PlayerStatsOut

    @classmethod
    def from_dataclass(cls, row: PlayerLeaderRow) -> PlayerLeaderRowOut:
        return cls(
            rank=row.rank,
            player_id=row.player_id,
            display_name=row.display_name,
            position=row.position,
            first_season=row.first_season,
            last_season=row.last_season,
            games=row.games,
            record=StarterRecordOut.from_dataclass(row.record),
            stats=PlayerStatsOut.from_dataclass(row.stats),
        )


class PlayerLeadersOut(BaseModel):
    sport: Sport
    # What the board ranks (#312). Qualifying is per category, so `total`
    # and the rows change with it, and `sort` belongs to exactly one.
    category: PlayerLeaderCategory
    season_type: PlayerSeasonType
    # Always the resolved sort: a request without one echoes the category's
    # default, which the engine picks.
    sort: PlayerLeaderSort
    limit: int
    offset: int
    # The whole qualifying population's size, so a client can page.
    total: int
    rows: list[PlayerLeaderRowOut]

    @classmethod
    def from_dataclass(cls, leaders: PlayerLeaders) -> PlayerLeadersOut:
        return cls(
            sport=leaders.sport,
            category=leaders.category,
            season_type=leaders.season_type,
            sort=leaders.sort,
            limit=leaders.limit,
            offset=leaders.offset,
            total=leaders.total,
            rows=[PlayerLeaderRowOut.from_dataclass(row) for row in leaders.rows],
        )


class PlayerSeasonLineOut(BaseModel):
    season: int
    season_type: PlayerSeasonType
    teams: list[str]
    games: int | None
    record: StarterRecordOut
    stats: PlayerStatsOut
    # Disclosure, not correction: completed games of this line's teams with
    # no player stat lines at all, which these totals therefore undercount.
    games_without_stat_lines: int

    @classmethod
    def from_dataclass(cls, line: PlayerSeasonLine) -> PlayerSeasonLineOut:
        return cls(
            season=line.season,
            season_type=line.season_type,
            teams=list(line.teams),
            games=line.games,
            record=StarterRecordOut.from_dataclass(line.record),
            stats=PlayerStatsOut.from_dataclass(line.stats),
            games_without_stat_lines=line.games_without_stat_lines,
        )


class PlayerCareerTotalsOut(BaseModel):
    season_type: PlayerSeasonType
    seasons: int
    games: int | None
    record: StarterRecordOut
    stats: PlayerStatsOut

    @classmethod
    def from_dataclass(cls, totals: PlayerCareerTotals) -> PlayerCareerTotalsOut:
        return cls(
            season_type=totals.season_type,
            seasons=totals.seasons,
            games=totals.games,
            record=StarterRecordOut.from_dataclass(totals.record),
            stats=PlayerStatsOut.from_dataclass(totals.stats),
        )


class PlayerCareerOut(BaseModel):
    sport: Sport
    player_id: int
    display_name: str
    position: str | None
    seasons: list[PlayerSeasonLineOut]
    # Null when the player has no season line of that type.
    regular_season: PlayerCareerTotalsOut | None
    postseason: PlayerCareerTotalsOut | None

    @classmethod
    def from_dataclass(cls, career: PlayerCareer) -> PlayerCareerOut:
        return cls(
            sport=career.sport,
            player_id=career.player_id,
            display_name=career.display_name,
            position=career.position,
            seasons=[PlayerSeasonLineOut.from_dataclass(line) for line in career.seasons],
            regular_season=(
                PlayerCareerTotalsOut.from_dataclass(career.regular_season)
                if career.regular_season is not None
                else None
            ),
            postseason=(
                PlayerCareerTotalsOut.from_dataclass(career.postseason)
                if career.postseason is not None
                else None
            ),
        )


# ---------------------------------------------------------------------------
# player comparison and search (issue #301) -- `cfb_strength.players`'
# comparison and search dataclasses, published by `api.players` under the
# same rules as the read layer above: field for field, the engine's order,
# and every optional value a required key that stays `null`. A head-to-head
# game's `a_stats`/`b_stats` is null when that player has no stat line in
# it, never a line of zeros. Nothing here compares `a` with `b`: no tally,
# winner or rate stat (founder decision, #301).
# ---------------------------------------------------------------------------


class PlayerHeadToHeadGameOut(BaseModel):
    season: int
    season_type: PlayerSeasonType
    week: int | None
    start_date: str | None
    source_id: str | None
    a_team: str
    b_team: str
    a_points: int
    b_points: int
    a_stats: PlayerStatsOut | None
    b_stats: PlayerStatsOut | None

    @classmethod
    def from_dataclass(cls, game: PlayerHeadToHeadGame) -> PlayerHeadToHeadGameOut:
        return cls(
            season=game.season,
            season_type=game.season_type,
            week=game.week,
            start_date=game.start_date,
            source_id=game.source_id,
            a_team=game.a_team,
            b_team=game.b_team,
            a_points=game.a_points,
            b_points=game.b_points,
            a_stats=(
                PlayerStatsOut.from_dataclass(game.a_stats) if game.a_stats is not None else None
            ),
            b_stats=(
                PlayerStatsOut.from_dataclass(game.b_stats) if game.b_stats is not None else None
            ),
        )


class PlayerHeadToHeadOut(BaseModel):
    season_type: PlayerSeasonType
    # `a`'s W-L-T against `b`.
    record: StarterRecordOut
    # Chronological, as the engine orders them.
    games: list[PlayerHeadToHeadGameOut]

    @classmethod
    def from_dataclass(cls, head_to_head: PlayerHeadToHead) -> PlayerHeadToHeadOut:
        return cls(
            season_type=head_to_head.season_type,
            record=StarterRecordOut.from_dataclass(head_to_head.record),
            games=[PlayerHeadToHeadGameOut.from_dataclass(g) for g in head_to_head.games],
        )


class PlayerComparisonOut(BaseModel):
    sport: Sport
    a: PlayerCareerOut
    b: PlayerCareerOut
    # Always present: 0-0-0 with no games when the two never met.
    regular_season_head_to_head: PlayerHeadToHeadOut
    postseason_head_to_head: PlayerHeadToHeadOut

    @classmethod
    def from_dataclass(cls, comparison: PlayerComparison) -> PlayerComparisonOut:
        return cls(
            sport=comparison.sport,
            a=PlayerCareerOut.from_dataclass(comparison.a),
            b=PlayerCareerOut.from_dataclass(comparison.b),
            regular_season_head_to_head=PlayerHeadToHeadOut.from_dataclass(
                comparison.regular_season_head_to_head
            ),
            postseason_head_to_head=PlayerHeadToHeadOut.from_dataclass(
                comparison.postseason_head_to_head
            ),
        )


class PlayerSearchRowOut(BaseModel):
    player_id: int
    display_name: str
    position: str | None
    first_season: int
    last_season: int

    @classmethod
    def from_dataclass(cls, row: PlayerSearchRow) -> PlayerSearchRowOut:
        return cls(
            player_id=row.player_id,
            display_name=row.display_name,
            position=row.position,
            first_season=row.first_season,
            last_season=row.last_season,
        )


class PlayerSearchOut(BaseModel):
    sport: Sport
    # The query as matched: stripped of surrounding whitespace.
    query: str
    limit: int
    rows: list[PlayerSearchRowOut]

    @classmethod
    def from_dataclass(cls, search: PlayerSearch) -> PlayerSearchOut:
        return cls(
            sport=search.sport,
            query=search.query,
            limit=search.limit,
            rows=[PlayerSearchRowOut.from_dataclass(row) for row in search.rows],
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


class MissingChampionErrorBody(BaseModel):
    """/champion's own error (issue #172), the one body here with no engine
    exception behind it: the year IS rated for `method`/`sport` (so it is
    not `unknown_year`), but no `rank = 1` row exists among its ratings.
    That is a data-integrity fault in the db, not a client mistake, so
    `api.errors` maps it to 500. Before #172 the route fell through to an
    empty team query and answered a 422 `ambiguous_team` listing every rated
    team as a candidate for a query the user never typed.

    `method` and `sport` are the request's literals, not bare `str`, for the
    same reason as `UnknownTeamErrorBody.sport`: the values are echoed from
    a validated request, and the schema should say so.
    """

    error: Literal["missing_champion"] = "missing_champion"
    year: int
    method: Method
    sport: Sport


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


class MissingChampionErrorResponse(BaseModel):
    detail: MissingChampionErrorBody


class UnknownPlayerErrorBody(BaseModel):
    """`GET /api/players/{player_id}` found no player with that id in that
    sport (issue #296, `contracts.UnknownPlayerError`). Echoes what was asked,
    like `UnknownTeamErrorBody`; `sport` is the request's validated literal."""

    error: Literal["unknown_player"] = "unknown_player"
    player_id: int
    sport: Sport


class UnknownPlayerErrorResponse(BaseModel):
    detail: UnknownPlayerErrorBody
