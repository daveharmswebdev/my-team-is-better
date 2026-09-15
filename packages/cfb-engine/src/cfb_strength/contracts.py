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
from typing import Literal, Protocol, get_args, runtime_checkable

# ---------------------------------------------------------------------------
# closed vocabularies (issue #112)
# ---------------------------------------------------------------------------

Sport = Literal["cfb", "nfl"]
"""Every league the engine ingests, rates and serves -- the one definition.

Before #112 this Literal was written out inline in this file,
evidence/proof.py and mcp_server/server.py, and apps/api and apps/web each
kept their own copy, with nothing checking that any pair agreed. apps/api now
imports this alias (contracts is on its permitted-import list), and apps/web's
union is checked against the API's published schema.

tests/test_contract_vocabularies.py ties it to what the engine actually runs:
`ratings.elo.ELO_CONFIGS`, `cli.INGEST_ENTRY_POINTS` and compute_ratings'
`--sport` choices must all equal it.
"""

Method = Literal["keener", "elo", "elo_career"]
"""Every rating method registered in `ratings.compute_ratings.METHODS`, in
display order (keener, the golden-dataset-validated default, first).

Declared here rather than derived from METHODS because apps/api may not import
`cfb_strength.ratings` (docs/ARCHITECTURE.md section 2). The boundary no longer
costs an unchecked copy: tests/test_contract_vocabularies.py fails if this
alias and METHODS disagree.
"""


def _require_known_sport(sport: str, row: str) -> None:
    """Runtime half of `Sport` for rows headed into the database. The
    annotation is static only, so an ingest path that hands an unlisted league
    through as a plain `str` would otherwise write rows that every downstream
    Literal silently disagrees with."""
    if sport not in get_args(Sport):
        valid = ", ".join(repr(s) for s in get_args(Sport))
        raise ValueError(f"{row}.sport={sport!r} is not a known league; expected one of {valid}")


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
    sport: Sport = "cfb"
    source_id: str | None = None

    def __post_init__(self) -> None:
        _require_known_sport(self.sport, "GameRow")


@dataclass(frozen=True)
class TeamRow:
    id: int
    school: str
    classification: str | None
    conference: str | None
    # See GameRow's sport/source_id note above -- same reasoning applies here.
    sport: Sport = "cfb"
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

    def __post_init__(self) -> None:
        _require_known_sport(self.sport, "TeamRow")


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
    sum(e.contribution for e in entries) + residual_contribution`, by
    construction (residual_contribution is defined as whatever's left over).

    That identity holds **for a method that produces a decomposition at
    all** -- which today means Keener. It is NOT a universal invariant of
    this dataclass, and reading it as one is a live trap: Elo returns the
    default-constructed `RatingBreakdown()` (no entries, zero residual)
    alongside a real rating of ~1500, so the sum is 0.0 and the identity is
    simply false there. Elo is a path through per-game K-scaled updates, not
    a sum of per-opponent contributions; there is no per-opponent
    decomposition to report, and inventing one would be fabrication rather
    than evidence. Elo's shown work is the path itself: `EloLedger`
    (issue #183), carried alongside this field, not squeezed into it.

    So an empty breakdown means "this method does not decompose", never
    "this team had no opponents". A consumer rendering a receipts panel must
    have an explicit empty state for it rather than showing a total of 0.00
    next to a non-zero rating -- tracked as #82, along with the display-scale
    problem the same surface has. `compute_ratings._store_breakdowns`
    deliberately writes no rows at all for a default-constructed breakdown,
    so the absence is visible in the database too, not just in Python.

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
class EloGameStep:
    """One game's Elo update, from one team's side: a single line of the
    shown work behind an Elo rating (issue #183).

    Every numeric field is the value `ratings/elo.py::_walk` actually used or
    produced while computing the rating, recorded as it happened, never a
    recomputation after the fact. From this team's side:

    - `home_field_adjustment` is `+hfa` at home, `-hfa` away, and `0.0` on a
      neutral field (`venue == "neutral"`).
    - `rating_gap == rating_before - opponent_rating_before +
      home_field_adjustment`: the engine's `elo_diff`, turned to face this
      team.
    - `win_expectancy` is this team's expected score before kickoff,
      `expected_score(rating_gap, cfg)`. The walk only evaluates the home
      side's, so the away side's is `1.0 -` the home side's and may differ
      from a direct evaluation in the last bit.
    - `mov_multiplier == mov_multiplier(team_points - opponent_points,
      rating_gap, result_score, cfg)`, where `result_score` is 1.0 / 0.5 /
      0.0 for "W" / "T" / "L". Both teams in a game carry the same value.
    - `shift == cfg.k * mov_multiplier * (result_score - win_expectancy)`,
      and is the exact negation of the opponent's shift for that game.
    - `rating_after == rating_before + shift`, bit for bit: it is the walk's
      own addition.

    Those formulas re-derive `win_expectancy`, `mov_multiplier` and `shift`
    from the step's own fields and its ledger's constants, within float
    tolerance. That property is what makes the panel checkable rather than
    decorative, and it is tested.

    `game_number` is 1-based, in the walk's order (the chronological total
    order `RatingMethod` guarantees). `opponent_name` defaults to `""` for
    the same reason as `OpponentCredit.opponent_name`: the ratings layer
    sees ids only, and the evidence layer fills it from `teams`.
    """

    game_number: int
    opponent_team_id: int
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
    week: int | None = None
    season_type: str = "regular"
    start_date: str | None = None
    opponent_name: str = ""


@dataclass(frozen=True)
class EloLedger:
    """The shown work behind one team's season Elo rating (issue #183): the
    rule's constants, the starting point, and every game's update in order.

    Identity, exact by construction: `steps[0].rating_before ==
    starting_rating`, each `steps[i + 1].rating_before ==
    steps[i].rating_after`, and `steps[-1].rating_after` is the team's
    rating. So `starting_rating + sum(step.shift for step in steps)` is the
    rating to float tolerance (the walk adds one shift at a time).

    It is not a per-opponent split like `RatingBreakdown` and does not
    pretend to be. Elo has none; it has a path, and the path is the evidence.

    The constants are the `EloConfig` fields the walk actually ran with,
    stored (`elo_ledger_configs`) rather than re-read from `ELO_CONFIGS` at
    display time, so a consumer can never print a tuning other than the one
    that produced the number. `mean` and `revert` are absent on purpose:
    season-isolated Elo never reverts.

    Produced only by `EloRating`. Keener has `RatingBreakdown` instead, and
    `EloCareerRating` produces none: a career ledger would also need
    offseason-reversion steps, which #183 leaves out of scope.
    """

    starting_rating: float
    k: float
    hfa: float
    scale: float
    mov_scale: float
    mov_autocorr: float
    steps: list[EloGameStep] = field(default_factory=list)


@dataclass(frozen=True)
class TeamRating:
    """One team's rating and its win-loss-tie record for the rated season.

    `ties` (issue #83): a **tie is a completed game with equal scores**, in
    every sport, counted identically by every rating method and by the
    evidence layer -- one definition, so a record can never read 6-9 in one
    place and 6-9-1 in another. It is required (no default) on purpose: a
    method that forgets to tally ties fails `mypy --strict` rather than
    silently reporting zero. `wins + losses + ties` equals the team's
    completed games with both scores in the season.

    This is the *reported record* only. It does not change how any method
    scores a tie -- Keener's credit math and Elo's `result == 0.5` already
    see every equal-score game.

    The definition is deliberately not sport-specific. CFB's completed
    0-0 rows for unreported small-school games are bad data, not ties; ingest
    writes those with NULL scores (issue #128,
    `ingest.normalize.is_unreported_result`), so no layer ever sees them as
    equal-score games and no per-sport exception is needed here.
    """

    team_id: int
    rating: float
    rank: int
    wins: int
    losses: int
    ties: int
    rating_breakdown: RatingBreakdown = field(default_factory=RatingBreakdown)
    # Issue #183: set by `EloRating` for every team it rates, None for every
    # other method. See `EloLedger`.
    elo_ledger: EloLedger | None = None


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
    - Each `TeamRating.wins`/`losses`/`ties` counts **only `target_season`
      games**. The rating carries across seasons; the record does not.

    `@runtime_checkable` is load-bearing, not decoration:
    `compute_ratings.compute_and_store` dispatches on
    `isinstance(impl, CareerRatingMethod)` to decide whether to load one
    season or the full history. An `isinstance` check against a method-only
    protocol tests for the presence of the method *name*, so a
    `RatingMethod`-only implementation (which has `rate` but no
    `rate_through`) correctly fails it.
    """

    def rate_through(self, games: list[Game], target_season: int) -> dict[int, TeamRating]: ...


# ---------------------------------------------------------------------------
# evidence output (evidence-agent implements the functions below against
# these shapes; mcp-agent imports and calls those functions -- see the
# "evidence public API" note at the bottom of this file for the exact
# function signatures the coordinator has assigned across that seam)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OpponentResult:
    # `games.id` (issue #218): the one per-game identity. A team can meet the
    # same opponent twice in a season (conference-title rematches; every NFL
    # division opponent), so `opponent_team_id` alone is not a key, and
    # `week` can be NULL. Consumers that list games key on this.
    game_id: int
    opponent_team_id: int
    opponent_name: str
    opponent_rank: int | None
    opponent_rating: float | None
    # "T" (issue #83): a completed game with equal scores -- the same
    # definition as `TeamRating.ties`. A tie is neither a quality win nor a
    # loss, so it is never selected as `quality_wins` or `worst_loss`, but it
    # always appears in `TeamCase.games`: before #83 it was silently dropped
    # from the receipts entirely.
    result: Literal["W", "L", "T"]
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
    # Read from `ratings.ties`, like wins/losses -- see `TeamRating.ties`.
    ties: int
    rating_breakdown: RatingBreakdown = field(default_factory=RatingBreakdown)
    games: list[OpponentResult] = field(default_factory=list)
    quality_wins: list[OpponentResult] = field(default_factory=list)
    worst_loss: OpponentResult | None = None
    # Issue #183: read back from `elo_ledger_steps`/`elo_ledger_configs`,
    # with every `opponent_name` filled. None when the method writes no
    # ledger (keener, elo_career); never an empty-steps ledger for a rated
    # team, since every rated team played at least one game.
    elo_ledger: EloLedger | None = None


@dataclass(frozen=True)
class ComparisonTeamSummary:
    """`_case_summary`'s shape, typed -- a `TeamCase` minus `year`/`method`/`games`."""

    team_id: int
    team_name: str
    rank: int
    rating: float
    wins: int
    losses: int
    ties: int
    rating_breakdown: RatingBreakdown = field(default_factory=RatingBreakdown)
    quality_wins: list[OpponentResult] = field(default_factory=list)
    worst_loss: OpponentResult | None = None
    # Issue #183: the same ledger as `TeamCase.elo_ledger`.
    elo_ledger: EloLedger | None = None


@dataclass(frozen=True)
class HeadToHeadMeeting:
    # `games.id` (issue #218) -- see `OpponentResult.game_id`.
    game_id: int
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
class CommonOpponentMeeting:
    """One game a compared side played against a shared opponent (issue #130).

    Team-relative, like `OpponentResult`: `result` and the score pair are from
    that side's perspective, so api/web never re-derive "which side am I".
    Deliberately not `HeadToHeadMeeting`, which is home/away-oriented with a
    `winner` name.
    """

    # `games.id` (issue #218) -- see `OpponentResult.game_id`.
    game_id: int
    result: Literal["W", "L", "T"]
    team_score: int
    opponent_score: int
    week: int | None
    season_type: str


@dataclass(frozen=True)
class CommonOpponent:
    """A team both compared sides played, with EVERY meeting per side.

    Before #130 this held one result/score pair per side, so a side that met
    the opponent twice (every NFL division opponent; CFB conference-title
    rematches) silently showed only its last meeting. Each list is non-empty
    and chronological: regular season by week, then postseason.

    No per-side W-L-T aggregate: it is derivable from the list, and one more
    thing that could disagree with it (founder decision on #130).
    """

    opponent_team_id: int
    opponent_name: str
    opponent_rank: int | None
    team_a_meetings: list[CommonOpponentMeeting]
    team_b_meetings: list[CommonOpponentMeeting]


@dataclass(frozen=True)
class ComparisonResult:
    year: int
    # The rating method both teams' ranks, ratings and `rating_diff` come from
    # (issue #152) -- `TeamCase.method`'s counterpart, so a compare verdict
    # says which engine answered it instead of the caller having to remember.
    method: Method
    team_a: ComparisonTeamSummary
    team_b: ComparisonTeamSummary
    head_to_head: HeadToHead
    common_opponents: list[CommonOpponent]
    rating_diff: float
    verdict: str


class AmbiguousTeamError(ValueError):
    """Raised by evidence.resolve_team when a query matches >1 team ambiguously.

    `candidates` is always non-empty -- "too many matches", never "none". A
    zero-match query is `UnknownTeamError` below; the two were conflated
    until issue #100, which produced an `ambiguous_team` payload carrying an
    empty candidate list and therefore a "did you mean:" prompt with nothing
    under it.
    """

    def __init__(self, query: str, candidates: list[str]):
        super().__init__(f"could not uniquely resolve {query!r}: candidates={candidates}")
        self.query = query
        self.candidates = candidates


class UnknownTeamError(ValueError):
    """Raised by evidence.resolve_team when a query matches *no* rated team
    for the requested year/sport (issue #100).

    Distinct from AmbiguousTeamError, which means the opposite problem. This
    fires in two real situations, and the caller cannot tell them apart from
    this error alone (nor does it need to): the name belongs to another
    league entirely ("Texas" under `sport="nfl"`), or it belongs to this
    league but has no rating row for this particular season (an FCS school
    in a year it wasn't rated). `UnknownYearError` already covers the third
    case -- the season has no ratings at all -- and is raised first.

    Only ever raised for a team the caller asked to *look up* -- a team-case
    `team`, or a comparison's `team_a`/`team_b`. A request's `user_team` is
    persona context and is never resolved.

    **Deliberately carries no suggestion list.** The first cut of #100 added
    one, built from a looser `difflib` pass over the rated names, and it
    could not work: `resolve_team`'s strict stage already resolves anything
    scoring >= 0.6, so this branch is reached only when *nothing* does, and
    the remaining [cutoff, 0.6) window holds noise rather than near-misses.
    Real typos never arrive here at all ("Alabma"/"Alabama" scores 0.9231
    and resolves upstream). Worse, no cutoff separates signal from noise:
    "Gonzaga"/"Georgia" scores 0.5714 and outranks "Texas"/"Houston Texans"
    at 0.5263 -- and the latter was itself a bad suggestion, since someone
    typing "Texas" under sport="nfl" wants the other league, not the Texans.
    Consumers therefore render a plain not-found state ("no rating for that
    season and league; try another season or switch leagues"), which is both
    honest and dead-end-free. A genuinely useful correction here would
    answer "which seasons *does* this team have?" -- a different query
    against unscoped team data, not a string-similarity heuristic.
    """

    def __init__(self, query: str, year: int, sport: Sport):
        super().__init__(f"no {sport} team matching {query!r} is rated for {year}")
        self.query = query
        self.year = year
        self.sport = sport


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
    # Pluralized when the Elo engine landed: this project now implements two
    # rating methods and PRD 5.6 makes crediting both a product requirement,
    # not a legal minimum. A list rather than a per-method lookup because the
    # About page credits every method the engine implements, not just the one
    # that answered the current question -- a reader deciding whether to
    # trust the rankings should see the whole basis, and `get_credits()`
    # stays argument-free and static.
    #
    # This is the same singular-to-plural shape change that broke AboutPage
    # in #69 when `data_source` became `data_sources`, so every consumer
    # moves in one commit: evidence/credits.py, mcp_server's asdict payload,
    # apps/api's CreditsOut, and apps/web's hand-maintained types.ts mirror.
    methodologies: list[MethodologyCredit]
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
#                     method: str = "keener", sport: Sport = "cfb") -> int: ...
#       Exact match first, then fuzzy match. Raises AmbiguousTeamError with
#       candidates on ambiguity, UnknownYearError if no ratings exist for
#       that year/method/sport.
#
#   def build_team_case(conn: sqlite3.Connection, year: int, team: str,
#                        method: str = "keener", sport: Sport = "cfb") -> TeamCase: ...
#       `team` is resolved via resolve_team. Raises the same two errors.
#
#   def build_comparison(conn: sqlite3.Connection, year: int, team_a: str,
#                         team_b: str, method: str = "keener",
#                         sport: Sport = "cfb") -> ComparisonResult: ...
#       Raises SameTeamComparisonError if team_a and team_b resolve to the same
#       team_id (added in the Round 4 amendment below).
#
#   def list_available_years(conn: sqlite3.Connection, method: str = "keener",
#                             sport: Sport = "cfb") -> list[int]: ...
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
# #102 amendment (epic #113): `sport` narrowed from `str` to
# `Literal["cfb", "nfl"]` on resolve_team/build_team_case/build_comparison and
# on UnknownTeamError.__init__, matching GameRow/TeamRow. Static only -- nothing
# enforces it at runtime; it matters because packages/cfb-engine now ships
# py.typed, so apps/api's call sites are type-checked against it.
# list_available_years keeps `str`: no #102 finding required narrowing it, and a
# single named `Sport` alias replacing all of these inline copies is #112's call.
#
# #112 amendment (epic #113): that alias is `Sport`, defined at the top of this
# file, and every signature above now uses it, list_available_years included.
# `Method` is declared beside it. GameRow/TeamRow also reject an unlisted league
# at construction, so ingested data cannot get ahead of the alias.
#
# mcp-agent imports these five names (plus AmbiguousTeamError/UnknownTeamError/
# UnknownYearError/SameTeamComparisonError from this file) from cfb_strength.evidence and must
# not reimplement their logic in mcp_server/.
# ---------------------------------------------------------------------------
