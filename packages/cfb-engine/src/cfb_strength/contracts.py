"""Every dataclass/Protocol that crosses a module boundary in this project.

Coordinator-owned. No spoke may edit this file. If a spoke's task needs a field
or shape that isn't here, that is a contract-insufficient finding it returns to
the coordinator -- it does not invent a parallel shape or import around this.

Layer map (enforced by .importlinter):
    cli / mcp_server
        -> evidence | ratings | ingest
            -> contracts | config | db

`ingest`, `ratings`, and `evidence` never import each other. The database
(schema.sql) is the integration boundary between them -- e.g. `evidence` reads
the `ratings` table via SQL rather than importing `cfb_strength.ratings`.
"""

from dataclasses import dataclass, field
from typing import Literal, Protocol, runtime_checkable


# ---------------------------------------------------------------------------
# ingest -> db normalization output (ingest-agent produces these, writes them
# to the `games`, `teams`, `team_season` tables per schema.sql)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GameRow:
    id: int
    season: int
    week: int | None
    season_type: str
    start_date: str | None
    neutral_site: bool
    completed: bool
    home_team_id: int
    away_team_id: int
    home_team: str
    away_team: str
    home_points: int | None
    away_points: int | None
    home_conference: str | None
    away_conference: str | None
    home_classification: str | None
    away_classification: str | None
    venue: str | None
    raw_json: str
    # sport/source_id added for #51 (NFL support, sprint 2). `sport` defaults to
    # "cfb" so the existing CFBD ingest path (ingest/normalize.py) needs no
    # change. `source_id` carries nflverse's native string id (team abbreviation
    # for teams, e.g. "KC"; composite game id, e.g. "2023_01_KC_DET", for games)
    # for traceability and idempotent re-ingest -- always None for CFB rows,
    # since CFBD ids are already the row's real integer primary key.
    sport: Literal["cfb", "nfl"] = "cfb"
    source_id: str | None = None


@dataclass(frozen=True)
class TeamRow:
    id: int
    school: str
    classification: str | None
    conference: str | None
    # See GameRow's sport/source_id note above -- same reasoning applies here.
    sport: Literal["cfb", "nfl"] = "cfb"
    source_id: str | None = None
    # mascot/alternate_names added for epic #76 (mascot- and city-searchable
    # team typeahead), populated by issue #77's CFBD `/teams` ingest path.
    #
    # `school` stays the canonical identity string and is NOT affected: it is
    # what the verdict lookup, the persona grounding check's known-team-names
    # universe, the golden dataset, and every cached narration key are keyed
    # on. These two fields are *display and search* metadata layered on top of
    # it -- "Texas" is still submitted and stored; "Longhorns" only helps a
    # user find it.
    #
    # Both default so the nflverse path (ingest/nflverse/normalize.py) and
    # the CFBD `/games`-derived path (ingest/normalize.py) keep constructing
    # `TeamRow` unchanged. NFL rows legitimately leave `mascot` None: their
    # `school` is already the full "New England Patriots" string, so city and
    # nickname are both substrings of the canonical name.
    #
    # `alternate_names` is a tuple (not a list) to keep the dataclass frozen
    # and hashable, consistent with every other field here. It holds CFBD's
    # `alternateNames` plus its `abbreviation` scalar, deduped -- e.g.
    # ("North Carolina St.", "NCSU", "NC State") for NC State. Persisted as a
    # JSON array in `teams.alternate_names`.
    mascot: str | None = None
    alternate_names: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# ratings input/output (ratings-agent implements RatingMethod; the CLI reads
# `games` from the db, the compute-and-store step writes to `ratings`)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Game:
    """One completed game, as handed to a `RatingMethod`.

    The four ordering fields below were added for the Elo engine. Only
    `season` is read by any current rating method (`EloCareerRating`, for
    its offseason boundaries); `week`, `season_type` and `start_date` are
    carried so a `Game` is self-describing when a failing test prints it,
    and so a future in-memory reorder needs no second contract change. The
    chronological ordering itself is imposed in SQL by
    `ratings/compute_ratings.py::_load_games`, not in Python.

    Every field is additive with a default, so no existing `Game(...)`
    construction changes and Keener -- which is order-invariant by
    construction, accumulating a credit matrix and then solving for its
    dominant eigenvector -- is unaffected in substance.

    Precisely how unaffected, because the honest bound matters more than a
    round claim: Keener is *exactly* reproducible on identical input, and
    reordering real games perturbs its ratings by at most ~1e-16 (measured
    at 1.39e-17 across all 55 ingested seasons, with **zero** rank
    changes). It is not bit-identical under reordering in general. A credit
    matrix cell accumulates one addend per meeting in *either* orientation,
    and unordered meetings do reach three in real data -- an NFL
    home-and-home plus a playoff rematch, or a CFB regular-season game plus
    a conference-championship rematch -- at which point float addition's
    non-associativity is reachable. See
    `ratings/test_keener.py`, where the two halves need different fixtures
    and different assertion strengths, so they are two tests:
    `test_keener_is_bit_identical_under_game_reordering` pins the exact
    two-meeting case, and `test_keener_reordering_drift_is_bounded_for_a_
    three_meeting_pair` pins the bound for the three-meeting case real data
    actually produces. The two golden-dataset regression suites remain the
    real guard.

    `season` is `None`-able rather than required because Keener genuinely
    does not need it and the synthetic `Game`s in the test suites do not
    populate it. `CareerRatingMethod` implementations DO need it and may
    treat a `None` season as a programming error.
    """

    home_team_id: int
    away_team_id: int
    home_points: int
    away_points: int
    neutral_site: bool = False
    season: int | None = None
    week: int | None = None
    season_type: str = "regular"
    start_date: str | None = None


@dataclass(frozen=True)
class OpponentCredit:
    """One opponent's exact contribution to a team's Keener rating.

    `credit` is the row-normalized (pre-epsilon) matrix value for this
    opponent -- purely game-based, straight from `_single_game_credit`,
    aggregated across every game the two teams played that season. `credit *
    opponent_rating == contribution`.

    `opponent_name` defaults to `""` because the ratings layer (`keener.py`)
    only ever sees team ids, never names -- it's the evidence layer, which
    already resolves names via the `teams` table for `OpponentResult`, that
    populates this field for real when it reconstructs `OpponentCredit` from
    the `rating_breakdowns` table. Never non-empty when it reaches apps/api
    or apps/web.

    `explanation` follows the same populated-by-evidence-not-ratings pattern,
    for the same reason: it is a plain-English-plus-numbers line (issue #37)
    describing *this opponent's* game(s) -- score, points-share, the flat
    win/loss base rate, and the resulting margin bonus, computed via
    `cfb_strength.credit_math.single_game_credit` against the raw score(s)
    `evidence/` already has loaded (from the same `games` table query behind
    `OpponentResult`). `keener.py` never sees a score-to-explanation mapping,
    only ids and points, so it cannot populate this field. Never empty when
    it reaches apps/api or apps/web (unlike `opponent_name`, there's no
    "resolution can fail" case here -- every entry has at least one game).
    """

    opponent_team_id: int
    games_played: int
    wins: int
    losses: int
    credit: float
    contribution: float
    opponent_name: str = ""
    explanation: str = ""


@dataclass(frozen=True)
class RatingBreakdown:
    """The exact per-opponent decomposition of a Keener rating: `rating ==
    sum(e.contribution for e in entries) + residual_contribution`, always,
    by construction (residual_contribution is defined as whatever's left
    over).

    `residual_contribution` is real math, not a rounding artifact, and it is
    NOT small: for a real FBS season (~120+ teams) it typically accounts for
    roughly half of a team's rating. Two things drive it, both inherent to
    the existing (already-validated, unmodified-by-this-feature) Keener
    implementation, not this decomposition: (1) `epsilon = 1/(2n)` is a
    fixed fraction (1/2) of the "equal share" baseline `1/n` for any n, by
    construction; (2) the credit matrix's dominant eigenvalue is meaningfully
    below 1 (keener.py's own docstring explains why: it deliberately avoids
    full row-stochastic normalization, which would erase real per-game
    credit information). Present this to users as a named, understood
    component of the rating system itself (e.g. "rating-system baseline /
    connectivity regularizer") -- never imply it's negligible or a rounding
    residue.
    """

    entries: list[OpponentCredit] = field(default_factory=list)
    residual_contribution: float = 0.0


@dataclass(frozen=True)
class TeamRating:
    team_id: int
    rating: float
    rank: int
    wins: int
    losses: int
    rating_breakdown: RatingBreakdown = field(default_factory=RatingBreakdown)


class RatingMethod(Protocol):
    """A rating algorithm that computes one season in isolation.

    Ordering guarantee (added with `Game`'s ordering fields, for Elo):
    `games` is delivered in chronological order -- by season, then regular
    season before postseason, then week, then start date, then game id (see
    `ratings/compute_ratings.py::_load_games`). The final id tiebreak makes
    that a *total* order, so a sequential method's output is reproducible
    even where `week`/`start_date` are null and the true chronology is
    unknown.

    Order-invariant methods (Keener) may ignore this and are unaffected by
    it. It is stated here because it is a promise the caller now keeps, and
    silently dropping it would break sequential methods in a way no
    Keener test would catch.
    """

    def rate(self, games: list[Game]) -> dict[int, TeamRating]: ...


@runtime_checkable
class CareerRatingMethod(Protocol):
    """A rating algorithm whose output for a season depends on prior seasons.

    `RatingMethod.rate()` is strictly per-year and cannot express carryover:
    it never sees a game outside the season being rated. This protocol is the
    seam for methods that can (e.g. Elo with cross-season rating carryover
    and offseason mean reversion).

    Semantics, which an implementation must honor exactly:

    - `games` spans every season up to *and including* `target_season`, in
      the chronological total order described on `RatingMethod`. Their
      `season` fields are populated.
    - The returned dict contains **only teams that played in
      `target_season`**. A team that appeared in an earlier season but not
      this one is carried through the replay (its rating still influences
      opponents) but is absent from the result.
    - Each `TeamRating.wins`/`losses` counts **only `target_season` games**.
      The rating carries across seasons; the win-loss record does not.

    `@runtime_checkable` is load-bearing, not decoration:
    `compute_ratings.compute_and_store` dispatches on
    `isinstance(impl, CareerRatingMethod)` to decide whether to load one
    season or the full history. An `isinstance` check against a method-only
    protocol tests for the presence of the method *name*, so a
    `RatingMethod`-only implementation (which has `rate` but no
    `rate_through`) correctly fails it.
    """

    def rate_through(
        self, games: list[Game], target_season: int
    ) -> dict[int, TeamRating]: ...


# ---------------------------------------------------------------------------
# evidence output (evidence-agent implements the functions below against
# these shapes; mcp-agent imports and calls those functions -- see the
# "evidence public API" note at the bottom of this file for the exact
# function signatures the coordinator has assigned across that seam)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OpponentResult:
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


@dataclass(frozen=True)
class TeamCase:
    year: int
    method: str
    team_id: int
    team_name: str
    rank: int
    rating: float
    wins: int
    losses: int
    rating_breakdown: RatingBreakdown = field(default_factory=RatingBreakdown)
    games: list[OpponentResult] = field(default_factory=list)
    quality_wins: list[OpponentResult] = field(default_factory=list)
    worst_loss: OpponentResult | None = None


@dataclass(frozen=True)
class ComparisonTeamSummary:
    """`_case_summary`'s shape, typed -- a `TeamCase` minus `year`/`method`/`games`."""

    team_id: int
    team_name: str
    rank: int
    rating: float
    wins: int
    losses: int
    rating_breakdown: RatingBreakdown = field(default_factory=RatingBreakdown)
    quality_wins: list[OpponentResult] = field(default_factory=list)
    worst_loss: OpponentResult | None = None


@dataclass(frozen=True)
class HeadToHeadMeeting:
    week: int | None
    season_type: str
    neutral_site: bool
    home_team: str
    away_team: str
    home_points: int
    away_points: int
    winner: str | None


@dataclass(frozen=True)
class HeadToHead:
    played: bool
    meetings: list[HeadToHeadMeeting] = field(default_factory=list)


@dataclass(frozen=True)
class CommonOpponent:
    opponent_team_id: int
    opponent_name: str
    opponent_rank: int | None
    team_a_result: Literal["W", "L"]
    team_a_score: int
    team_a_opponent_score: int
    team_b_result: Literal["W", "L"]
    team_b_score: int
    team_b_opponent_score: int


@dataclass(frozen=True)
class ComparisonResult:
    year: int
    team_a: ComparisonTeamSummary
    team_b: ComparisonTeamSummary
    head_to_head: HeadToHead
    common_opponents: list[CommonOpponent]
    rating_diff: float
    verdict: str


class AmbiguousTeamError(ValueError):
    """Raised by evidence.resolve_team when a query matches >1 team ambiguously."""

    def __init__(self, query: str, candidates: list[str]):
        super().__init__(f"could not uniquely resolve {query!r}: candidates={candidates}")
        self.query = query
        self.candidates = candidates


class UnknownYearError(ValueError):
    """Raised by evidence functions when no ratings exist for the requested year."""

    def __init__(self, year: int, available_years: list[int]):
        super().__init__(f"no ratings computed for {year}")
        self.year = year
        self.available_years = available_years


class SameTeamComparisonError(ValueError):
    """Raised by build_comparison when team_a and team_b resolve to the same team."""

    def __init__(self, team_name: str):
        super().__init__(f"cannot compare {team_name!r} to itself")
        self.team_name = team_name


# ---------------------------------------------------------------------------
# Attribution (static; no db access). Mirrors the shape mcp_server's
# credits_resource() already returns -- see get_credits() in
# evidence/credits.py, the single source of truth both mcp_server and
# apps/api import from (PRD §5.6 / ARCHITECTURE §4.5).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MethodologyCredit:
    name: str
    citation: str
    url: str
    summary: str


@dataclass(frozen=True)
class DataSourceCredit:
    name: str
    url: str
    note: str


@dataclass(frozen=True)
class Credits:
    methodology: MethodologyCredit
    data_sources: list[DataSourceCredit]


# ---------------------------------------------------------------------------
# Evidence public API (coordinator-assigned function signatures)
#
# These functions are NOT implemented in this file -- they live in
# src/cfb_strength/evidence/proof.py, owned by evidence-agent. They are
# declared here as the seam's interface so evidence-agent and mcp-agent can
# be briefed and built in parallel without either one guessing the other's
# shape:
#
#   def resolve_team(conn: sqlite3.Connection, year: int, query: str,
#                     method: str = "keener", sport: str = "cfb") -> int: ...
#       Exact match first, then fuzzy match. Raises AmbiguousTeamError with
#       candidates on ambiguity, UnknownYearError if no ratings exist for
#       that year/method/sport.
#
#   def build_team_case(conn: sqlite3.Connection, year: int, team: str,
#                        method: str = "keener", sport: str = "cfb") -> TeamCase: ...
#       `team` is resolved via resolve_team. Raises the same two errors.
#
#   def build_comparison(conn: sqlite3.Connection, year: int, team_a: str,
#                         team_b: str, method: str = "keener",
#                         sport: str = "cfb") -> ComparisonResult: ...
#       Raises SameTeamComparisonError if team_a and team_b resolve to the same
#       team_id (added in the Round 4 amendment below).
#
#   def list_available_years(conn: sqlite3.Connection, method: str = "keener",
#                             sport: str = "cfb") -> list[int]: ...
#       `SELECT DISTINCT year FROM ratings WHERE method = ? AND sport = ? ORDER
#       BY year`. Added in the Round 4 amendment below: mcp-agent and
#       evidence-agent had each independently implemented an identical private
#       copy of this query (`_available_years`) because it wasn't originally
#       part of the public API — `reviewer` flagged the duplication as an
#       uncovered seam. Promoted here so there is exactly one implementation
#       (evidence-agent's), which mcp-agent imports instead of reimplementing.
#
#   def get_credits() -> Credits: ...
#       Lives in evidence/credits.py, not proof.py (no db access, unlike the
#       four functions above). Added for #29/#30: relocates the dict literal
#       that used to live inline in mcp_server/server.py's credits_resource()
#       so apps/api can import the same source of truth instead of
#       hardcoding a second copy (ARCHITECTURE §4.5). Content must match the
#       pre-existing inline dict verbatim -- this is a relocation, not new
#       copy.
#
# Round 5 amendment (#58, sprint 2 NFL support): `sport: str = "cfb"` added to
# resolve_team/build_team_case/build_comparison/list_available_years, mirroring
# the `sport` column added to ratings/games/teams/rating_breakdowns in #51 and
# already threaded through compute_ratings.py in #57. Every one of these
# functions currently scopes its SQL by `year`/`method` alone with no `sport`
# filter -- the same cross-sport row-bleed bug class #57 fixed in ratings
# (a CFB and an NFL season sharing a year value would blend into one team
# pool/win-graph). Default preserves existing CFB-only callers' behavior
# unmodified. No classification-based (FBS/FCS) filtering exists in
# evidence/proof.py today -- quality-win/worst-loss logic keys off
# `ratings.rank`, which is already sport- and classification-scoped upstream
# by compute_ratings.py -- so evidence-agent's classification-NULL handling is
# about not assuming/erroring on NULL `teams.classification` values it reads
# incidentally (e.g. team listings), not about new tiering logic here.
#
# mcp-agent imports these five names (plus AmbiguousTeamError/UnknownYearError/
# SameTeamComparisonError from this file) from cfb_strength.evidence and must
# not reimplement their logic in mcp_server/.
# ---------------------------------------------------------------------------
