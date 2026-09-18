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

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
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
# player stats (issue #289, epic #288): ingest -> db rows for the `players`,
# `player_source_ids`, `game_starters`, `player_game_stats` and
# `player_season_stats` tables per schema.sql
# ---------------------------------------------------------------------------

PlayerSeasonType = Literal["regular", "postseason"]
"""The same two values `games.season_type` holds. A source's own spelling
(nflverse's "REG"/"POST") is translated at ingest, never stored."""


def _require_non_empty(value: str, row: str, name: str) -> None:
    if not value:
        raise ValueError(f"{row}.{name} must be non-empty")


@dataclass(frozen=True)
class PlayerStats:
    """The stat columns shared, in this order, by `player_game_stats` and
    `player_season_stats` (tests/test_player_schema.py checks the DDL
    against this class). Adding a stat means a field here and a column on
    both tables.

    None means the source did not track the stat, never zero: an era
    before a stat was recorded must not read as a player who had none.

    Order is append-only. Both tables pin these as their *trailing*
    columns, and a pre-existing db reaches the same shape through
    `connection._migrate_player_stat_columns`, whose ALTER TABLE can only
    append -- so a field inserted in the middle would give a fresh db and a
    migrated one different column orders.

    Every column here is a whole number in the source. Deliberately absent:
    rate columns (`fg_pct`, `pat_pct`) are derived from the counts beside
    them, and nflverse's `def_sacks` is fractional (0.5 for a shared sack),
    which the integer parse would reject -- the defensive columns arrive in
    their own widening once #316 has verified them, and that round has to
    settle the fractional case (#317).

    Issue #298 -- the sign convention, previously unstated: yardage a
    player *lost* is stored **positive**, so `sack_yards_lost` reads the way
    its name and an official stat line read (Brady 2007: 21 sacks, 128
    yards). nflverse publishes it signed negative, so the ingest negates it.
    """

    # Passing (issue #289).
    completions: int | None = None
    attempts: int | None = None
    passing_yards: int | None = None
    passing_tds: int | None = None
    passing_interceptions: int | None = None
    sacks_suffered: int | None = None
    sack_yards_lost: int | None = None
    # Rushing: the first three from #289, the rest from #313.
    carries: int | None = None
    rushing_yards: int | None = None
    rushing_tds: int | None = None
    rushing_first_downs: int | None = None
    rushing_fumbles_lost: int | None = None
    # Receiving (#313). `receiving_air_yards` and
    # `receiving_yards_after_catch` are deliberately left out: measured on
    # the raw weekly files, they carry 506 and 108 non-zero rows in 1999
    # against 4,468 and 3,762 in 2023, so a career spanning the gap would
    # compare an era that tracked them against one that didn't.
    receptions: int | None = None
    targets: int | None = None
    receiving_yards: int | None = None
    receiving_tds: int | None = None
    receiving_first_downs: int | None = None
    receiving_fumbles_lost: int | None = None
    # Kicking (#313). The `fg_made_*` buckets partition `fg_made` by
    # distance; `fg_made_60_` keeps nflverse's trailing underscore rather
    # than inventing a tidier name the projection would have to translate.
    # A 0 in the 60+ bucket is a real zero (nobody made one in 1999), not an
    # untracked stat.
    fg_made: int | None = None
    fg_att: int | None = None
    fg_long: int | None = None
    fg_made_0_19: int | None = None
    fg_made_20_29: int | None = None
    fg_made_30_39: int | None = None
    fg_made_40_49: int | None = None
    fg_made_50_59: int | None = None
    fg_made_60_: int | None = None
    pat_made: int | None = None
    pat_att: int | None = None
    # Punting (#313).
    pt_att: int | None = None
    pt_yards: int | None = None
    pt_net_yards: int | None = None
    pt_long: int | None = None
    pt_inside_20: int | None = None


PLAYER_STAT_MAX_FIELDS: frozenset[str] = frozenset({"fg_long", "pt_long"})
"""The `PlayerStats` columns whose season total is the MAX of the game
rows, not the sum (issue #313).

Every other column is a count or a yardage that adds up over a season. A
"long" does not: summing a kicker's 16 game-long field goals would report a
season long of several hundred yards. They are stored anyway, rather than
left out of season rows, because "longest field goal" is a leaders column in
its own right (#315).

Named here rather than in the ingest because both halves of the boundary
need it -- the ingest aggregates by it, and any later reader combining
seasons into a career has to combine these the same way. Kept as a set of
names, not a per-field enum, because MAX is the only exception so far;
tests/test_player_schema.py checks every name is a real `PlayerStats` field.
"""


@dataclass(frozen=True)
class PlayerRow:
    """One person in one sport. Identity across data sources is carried by
    `PlayerSourceIdRow`, not by this row; the same person in CFB and the
    NFL is two rows (linking them is out of scope, epic #288)."""

    id: int
    display_name: str
    position: str | None
    birth_date: str | None
    sport: Sport

    def __post_init__(self) -> None:
        _require_known_sport(self.sport, "PlayerRow")
        _require_non_empty(self.display_name, "PlayerRow", "display_name")


@dataclass(frozen=True)
class PlayerSourceIdRow:
    """A source's own id for a player, e.g. ("gsis", "00-0010346") or
    ("pfr", "MannPe00"). This is the crosswalk that lets a later source
    (Pro Football Reference for pre-1999 seasons, CFBD for college) attach
    to an existing player instead of minting a duplicate."""

    player_id: int
    source: str
    source_id: str

    def __post_init__(self) -> None:
        _require_non_empty(self.source, "PlayerSourceIdRow", "source")
        _require_non_empty(self.source_id, "PlayerSourceIdRow", "source_id")


@dataclass(frozen=True)
class GameStarterRow:
    """The player who started a game at `position` for `team_id`. `source`
    names where that claim came from, because sources disagree about
    starters and a record-as-starter is only as good as this row."""

    game_id: int
    team_id: int
    position: str
    player_id: int
    source: str
    sport: Sport

    def __post_init__(self) -> None:
        _require_known_sport(self.sport, "GameStarterRow")
        _require_non_empty(self.position, "GameStarterRow", "position")
        _require_non_empty(self.source, "GameStarterRow", "source")


@dataclass(frozen=True)
class PlayerGameStatRow:
    """One player's stat line in one game, for the team they played for in
    that game (which is how traded players and transfers stay correct)."""

    player_id: int
    game_id: int
    team_id: int
    sport: Sport
    stats: PlayerStats

    def __post_init__(self) -> None:
        _require_known_sport(self.sport, "PlayerGameStatRow")


@dataclass(frozen=True)
class PlayerSeasonStatRow:
    """A player's season totals for one season type. Stored in its own
    right rather than only summed from game rows, because older eras have
    season totals and no game logs.

    `team_id` is None when the totals span more than one team or the source
    doesn't say; per-team splits come from `PlayerGameStatRow`. One row per
    (player, season, season_type) whatever the source, so two sources can
    never double a career total."""

    player_id: int
    season: int
    season_type: PlayerSeasonType
    team_id: int | None
    games: int | None
    source: str
    sport: Sport
    stats: PlayerStats

    def __post_init__(self) -> None:
        _require_known_sport(self.sport, "PlayerSeasonStatRow")
        _require_non_empty(self.source, "PlayerSeasonStatRow", "source")
        if self.season_type not in get_args(PlayerSeasonType):
            valid = ", ".join(repr(s) for s in get_args(PlayerSeasonType))
            raise ValueError(
                f"PlayerSeasonStatRow.season_type={self.season_type!r}; expected one of {valid}"
            )


# ---------------------------------------------------------------------------
# player read layer (issue #296, epic #288 step 2): `cfb_strength.players`
# reads the tables above and returns these; apps/api publishes them. No rating
# math: a leaderboard is a stat column sorted descending.
#
# Coordinator-assigned signatures, implemented by players-agent and exported
# from `cfb_strength.players`:
#
#   def get_player_leaders(conn: sqlite3.Connection, *, sport: Sport,
#                          category: PlayerLeaderCategory = "passing",
#                          season_type: PlayerSeasonType = "regular",
#                          sort: PlayerLeaderSort | None = None,
#                          limit: int = 50, offset: int = 0) -> PlayerLeaders: ...
#       `sort=None` means the category's first sort in
#       PLAYER_LEADER_SORTS_BY_CATEGORY. Raises ValueError unless
#       1 <= limit <= PLAYER_LEADERS_MAX_LIMIT, offset >= 0, and `sort` is one
#       of `category`'s sorts (#312).
#
#   def get_player_career(conn: sqlite3.Connection, *, sport: Sport,
#                         player_id: int) -> PlayerCareer: ...
#       Raises UnknownPlayerError when no `players` row has that id and sport.
#
# Rules both functions share:
#   * Totals come from `player_season_stats` (older eras have season totals
#     and no game logs); W-L-T comes from `game_starters` joined to completed
#     games with both scores.
#   * A summed stat is None when any season row it sums is NULL for that stat,
#     or when there are no season rows: a partial total must not read as a
#     career. (No 1999-2025 nflverse row is NULL; the rule is for later
#     sources.)
#   * A leaders row and the same player's career totals for that season type
#     agree exactly (games, record, every stat), and a career's totals equal
#     the sum of its season lines.
#   * Round-1 readings, accepted (#296): a season line that has a QB start
#     but no season row carries None stats and games, so every total that
#     covers it is None too (a gap stays visible rather than shrinking a
#     career). Any QB `game_starters` row counts as a start for a line's
#     existence and for qualifying; only completed games with both scores
#     count toward W-L-T. Neither case occurs in 1999-2025 nflverse data.
# ---------------------------------------------------------------------------

PlayerLeaderCategory = Literal["passing", "rushing"]
"""What a leaderboard ranks (epic #311, decision 1): a stat category, not a
position. A board ranks every player with the category's base stat, whatever
their position, so a QB's carries count on the rushing board.

Qualifying (decision 2), per season type, with no minimum:
  * passing: at least one pass attempt, or one QB start (#296);
  * rushing: at least one carry (#312)."""

PlayerLeaderSort = Literal[
    "passing_yards", "passing_tds", "wins", "rushing_yards", "rushing_tds", "carries"
]
"""Every leaderboard sort. With `PlayerSeasonType` the passing ones cover
passing yards, passing TDs, regular-season starter wins and playoff starter
wins. Always descending; ties break by `display_name`, then `player_id`."""

PLAYER_LEADER_SORTS_BY_CATEGORY: Mapping[PlayerLeaderCategory, tuple[PlayerLeaderSort, ...]] = (
    MappingProxyType(
        {
            "passing": ("passing_yards", "passing_tds", "wins"),
            "rushing": ("rushing_yards", "rushing_tds", "carries"),
        }
    )
)
"""The sorts each category accepts, its default first. Every
`PlayerLeaderSort` belongs to exactly one category."""

PLAYER_LEADERS_MAX_LIMIT = 100


@dataclass(frozen=True)
class StarterRecord:
    """W-L-T in the games a player started at QB (`game_starters`), counting
    completed games with both scores. A tie is equal scores, the same
    definition as `TeamRating.ties` (#83)."""

    wins: int
    losses: int
    ties: int

    @property
    def starts(self) -> int:
        return self.wins + self.losses + self.ties


@dataclass(frozen=True)
class PlayerLeaderRow:
    """One qualifying player on a leaderboard for one category and season
    type. Qualifying is per category (`PlayerLeaderCategory`), with no
    minimum: every board is a counting stat (#296, #312). `record` is the
    player's QB starter record whatever the category (0-0-0 for most
    rushers)."""

    # Competition ranking on the sort value (1, 2, 2, 4) across the whole
    # qualifying population, not the page. None when the sort value is None;
    # those rows sort after every ranked row.
    rank: int | None
    player_id: int
    display_name: str
    position: str | None
    # The span of seasons with a season row or a start in this season type.
    first_season: int
    last_season: int
    # Sum of `player_season_stats.games`; None under the NULL rule above.
    games: int | None
    record: StarterRecord
    stats: PlayerStats


@dataclass(frozen=True)
class PlayerLeaders:
    sport: Sport
    category: PlayerLeaderCategory
    season_type: PlayerSeasonType
    # Always the resolved sort, never None: a request without one echoes its
    # category's default.
    sort: PlayerLeaderSort
    limit: int
    offset: int
    # Size of the whole qualifying population, so a client can page.
    total: int
    rows: list[PlayerLeaderRow]


@dataclass(frozen=True)
class PlayerSeasonLine:
    """A player's season in one season type: a line exists when the player has
    a season row or at least one start in it."""

    season: int
    season_type: PlayerSeasonType
    # `teams.school` for every team the player has a stat line or a start for
    # in this season and season type, in order of first game. Falls back to
    # the season row's team when there are no game rows; empty when neither
    # names one.
    teams: list[str]
    games: int | None
    record: StarterRecord
    # All None when the player started games but has no season row.
    stats: PlayerStats
    # Disclosure, not correction (#289's accepted limit): completed games in
    # this season and season type played by one of this line's teams that
    # have no `player_game_stats` rows at all, so these totals undercount
    # them (e.g. Warner 1999: 1999_01_BAL_STL).
    games_without_stat_lines: int


@dataclass(frozen=True)
class PlayerCareerTotals:
    season_type: PlayerSeasonType
    # Number of season lines of this type.
    seasons: int
    games: int | None
    record: StarterRecord
    stats: PlayerStats


@dataclass(frozen=True)
class PlayerCareer:
    sport: Sport
    player_id: int
    display_name: str
    position: str | None
    # Chronological; within a season, regular before postseason.
    seasons: list[PlayerSeasonLine]
    # None when the player has no line of that type.
    regular_season: PlayerCareerTotals | None
    postseason: PlayerCareerTotals | None


class UnknownPlayerError(ValueError):
    """Raised by `players.get_player_career` when no player has that id in
    that sport."""

    def __init__(self, player_id: int, sport: Sport):
        super().__init__(f"no {sport} player with id {player_id}")
        self.player_id = player_id
        self.sport = sport


# ---------------------------------------------------------------------------
# player comparison and search (issue #301, epic #288 step 3): the same
# module (`cfb_strength.players`) and the same rules as the read layer above.
#
# Coordinator-assigned signatures, implemented by players-agent and exported
# from `cfb_strength.players`:
#
#   def get_player_comparison(conn: sqlite3.Connection, *, sport: Sport,
#                             a: int, b: int) -> PlayerComparison: ...
#       Raises ValueError when a == b, and UnknownPlayerError for the first of
#       `a`, `b` (checked in that order) with no `players` row in that sport.
#
#   def search_players(conn: sqlite3.Connection, *, sport: Sport, query: str,
#                      limit: int = 10) -> PlayerSearch: ...
#       Raises ValueError unless 1 <= limit <= PLAYER_SEARCH_MAX_LIMIT and
#       `query.strip()` has at least PLAYER_SEARCH_MIN_QUERY_LENGTH characters.
#
# Rules:
#   * `PlayerComparison.a` and `.b` equal `get_player_career` for those ids.
#     A comparison computes no totals of its own, so it can never disagree
#     with a career page.
#   * Head-to-head (founder decision, #301): a completed game with both scores
#     in which `a` and `b` each have a QB `game_starters` row, for different
#     teams. Relief appearances don't count; when the source lists a
#     replacement starter, the game belongs to the replacement. The record is
#     `a`'s W-L-T in those games (a tie is equal scores), so swapping `a` and
#     `b` swaps wins and losses. `record.starts == len(games)`, and every such
#     game is also counted in each player's career record for its season type.
#   * No rating math (founder decision, #301): nothing here compares `a`'s
#     numbers with `b`'s. Marking the larger number in a row is presentation
#     in apps/web, and there is no tally, winner or rate stat.
#   * Search matches `display_name` case-insensitively as a substring of the
#     stripped query, among players who qualify for a leaderboard in either
#     season type (a pass attempt or a QB start). Order: regular-season career
#     passing yards descending with None last, then `display_name`, then
#     `player_id`.
# ---------------------------------------------------------------------------

PLAYER_SEARCH_MAX_LIMIT = 20
PLAYER_SEARCH_MIN_QUERY_LENGTH = 2


@dataclass(frozen=True)
class PlayerHeadToHeadGame:
    """One game `a` and `b` started against each other at QB. (Not the
    evidence layer's team `HeadToHead` above.)"""

    season: int
    season_type: PlayerSeasonType
    week: int | None
    start_date: str | None
    # `games.source_id`, e.g. "1999_21_STL_TEN"; None when the source has none.
    source_id: str | None
    # `teams.school` for the team each player started for.
    a_team: str
    b_team: str
    a_points: int
    b_points: int
    # Each player's `player_game_stats` line in this game; None when the
    # player has no row (e.g. the games with no stat lines at all, #289's
    # accepted limit). A row's untracked stat stays None inside PlayerStats.
    a_stats: PlayerStats | None
    b_stats: PlayerStats | None


@dataclass(frozen=True)
class PlayerHeadToHead:
    season_type: PlayerSeasonType
    # `a`'s W-L-T against `b`.
    record: StarterRecord
    # Chronological: start_date, then week, then game id.
    games: list[PlayerHeadToHeadGame]


@dataclass(frozen=True)
class PlayerComparison:
    sport: Sport
    a: PlayerCareer
    b: PlayerCareer
    # Always present; `record` is 0-0-0 and `games` empty when they never met.
    regular_season_head_to_head: PlayerHeadToHead
    postseason_head_to_head: PlayerHeadToHead


@dataclass(frozen=True)
class PlayerSearchRow:
    player_id: int
    display_name: str
    position: str | None
    # The span of seasons with a season row or a QB start, either season type,
    # so two players with one name can be told apart.
    first_season: int
    last_season: int


@dataclass(frozen=True)
class PlayerSearch:
    sport: Sport
    # The query as matched: stripped of surrounding whitespace.
    query: str
    limit: int
    rows: list[PlayerSearchRow]


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
    # Issue #194: the margin-of-victory denominator floor, as a fraction of
    # `mov_scale` (`ratings/elo.py::_MIN_DENOM_FRACTION`), stored with the
    # other constants so a panel prints the floor the walk actually used
    # instead of hard-coding "half". Same rule as every field above: read
    # back from `elo_ledger_configs`, never re-read from the module constant.
    mov_denom_floor_fraction: float
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
    # Where this team played the game (issue #294). Same vocabulary and same
    # meaning as `EloGameStep.venue` -- this team's side, NOT the stadium
    # name. (`GameRow.venue` is the stadium name; the collision is
    # pre-existing and deliberate on the Elo side, so match it here rather
    # than invent a third spelling.)
    #
    # `neutral_site` is kept alongside it, not replaced by a property, for
    # one concrete reason: `mcp_server/server.py` serialises team cases with
    # `dataclasses.asdict`, which skips properties, so a property would drop
    # the field from the MCP payload silently. The two are kept honest by
    # `__post_init__` instead, and there is exactly one construction site
    # (`evidence/proof.py::_opponent_result`) to keep in step.
    venue: Literal["home", "away", "neutral"]
    neutral_site: bool

    def __post_init__(self) -> None:
        if self.neutral_site != (self.venue == "neutral"):
            raise ValueError(
                f"OpponentResult venue/neutral_site disagree: venue={self.venue!r}, "
                f"neutral_site={self.neutral_site!r} (game_id={self.game_id})"
            )


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
    # Issue #294, and team-relative like everything else here. A meeting is a
    # straight projection of that side's `OpponentResult`
    # (`_meetings_by_opponent`), so this is that row's `venue` copied, never
    # re-derived. No `neutral_site` companion: this shape never had one, so
    # nothing reads it, and `venue == "neutral"` says the same thing.
    venue: Literal["home", "away", "neutral"]


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
    # Issue #144: the registered rating methods this citation covers, so the
    # credits can be checked against the engine's method registry instead of
    # trusting a hand-kept list. Not 1:1 by name -- `elo` and `elo_career`
    # share one Elo citation -- so the invariant is on the union: every
    # `get_args(Method)` value is covered by exactly one credit, and no credit
    # names a method that isn't registered (`compute_ratings.METHODS`).
    # `methods[0]` is the credit's stable id downstream (the About page's
    # article anchor, `/about#elo`), which is why this is an ordered tuple
    # and never a set. Published as-is through apps/api's `CreditsOut` and
    # apps/web's `types.ts` mirror.
    methods: tuple[Method, ...]


@dataclass(frozen=True)
class DataSourceCredit:
    # Issue #296: a stable, unique id ("cfbd", "nflverse_games",
    # "nflverse_player_stats"), so a page that shows one source's data can
    # pick that source's credit without keying on a display name that could
    # be reworded -- the role `MethodologyCredit.methods[0]` plays for methods.
    id: str
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
