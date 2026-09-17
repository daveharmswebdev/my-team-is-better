"""The SQL both player read functions share (#296).

One definition of a season line and one of a total, so a leaderboard row and
the same player's career totals are the same aggregate by construction, not
two queries that happen to agree.

Every fragment here is a fixed string; the only values that vary reach SQLite
as bound parameters (`:sport`, `:season_type`, `:player_id`).
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from cfb_strength.contracts import (
    PLAYER_STAT_MAX_FIELDS,
    PlayerLeaderCategory,
    PlayerStats,
)

STAT_COLUMNS: tuple[str, ...] = tuple(PlayerStats.__dataclass_fields__)

# The one statement of each leaderboard category's qualifying rule, as a
# condition on a season line of `lines`, per season type with no minimum
# (`PlayerLeaderCategory`). A NULL stat never qualifies a line.
QUALIFYING: Mapping[PlayerLeaderCategory, str] = MappingProxyType(
    {
        # A pass attempt, or a QB start (#296).
        "passing": "attempts > 0 OR start_rows > 0",
        # A carry, whatever the position (#312).
        "rushing": "carries > 0",
    }
)

# A start counts toward W-L-T only in a completed game with both scores.
_COUNTED = "g.completed = 1 AND g.home_points IS NOT NULL AND g.away_points IS NOT NULL"
_MINE = "CASE WHEN s.team_id = g.home_team_id THEN g.home_points ELSE g.away_points END"
_THEIRS = "CASE WHEN s.team_id = g.home_team_id THEN g.away_points ELSE g.home_points END"


def null_aware_sum(column: str) -> str:
    """SUM, except None when any summed row is NULL for `column`. SQL's own
    SUM skips NULLs, which would turn an untracked season into a partial
    total that reads as a career."""
    return f"CASE WHEN COUNT({column}) = COUNT(*) THEN SUM({column}) END"


def stat_total(column: str) -> str:
    """How a stat column combines several season lines into one total: the
    null-aware SUM, except plain MAX for `contracts.PLAYER_STAT_MAX_FIELDS`
    (issue #334). A "long" does not add up -- a kicker whose three season
    longs are 53, 47 and 52 has a career long of 53, not 152.

    The MAX is deliberately *not* null-aware. SQL's MAX skips NULLs and is
    NULL over an all-NULL group, which is what a long wants: a player with
    one kicking season keeps that season's long instead of losing it to the
    seasons he never kicked in. A total that adds up can't do that, because
    an untracked season would read as a partial career.

    The column set comes from the contract, never a list here, so a third
    MAX column is handled without touching this module.
    """
    if column in PLAYER_STAT_MAX_FIELDS:
        return f"MAX({column})"
    return null_aware_sum(column)


def lines_cte(*, by_player: bool, by_season_type: bool) -> str:
    """`WITH ... lines AS (...)`: one row per (player, season, season_type)
    with a season row or a QB start, scoped to `:sport` and optionally to
    `:player_id` and `:season_type`. A line with no season row carries NULL
    for `games` and every stat."""
    starter_filters = ["s.sport = :sport", "g.sport = :sport", "s.position = 'QB'"]
    row_filters = ["sport = :sport"]
    if by_player:
        starter_filters.append("s.player_id = :player_id")
        row_filters.append("player_id = :player_id")
    if by_season_type:
        starter_filters.append("g.season_type = :season_type")
        row_filters.append("season_type = :season_type")
    else:
        starter_filters.append("g.season_type IN ('regular', 'postseason')")
    stats = ", ".join(f"r.{c}" for c in STAT_COLUMNS)
    return f"""
    WITH starts AS (
        SELECT s.player_id, g.season, g.season_type,
               COUNT(*) AS start_rows,
               SUM(CASE WHEN {_COUNTED} AND {_MINE} > {_THEIRS} THEN 1 ELSE 0 END) AS wins,
               SUM(CASE WHEN {_COUNTED} AND {_MINE} < {_THEIRS} THEN 1 ELSE 0 END) AS losses,
               SUM(CASE WHEN {_COUNTED} AND {_MINE} = {_THEIRS} THEN 1 ELSE 0 END) AS ties
        FROM game_starters s
        JOIN games g ON g.id = s.game_id
        WHERE {" AND ".join(starter_filters)}
        GROUP BY s.player_id, g.season, g.season_type
    ),
    season_rows AS (
        SELECT * FROM player_season_stats WHERE {" AND ".join(row_filters)}
    ),
    line_keys AS (
        SELECT player_id, season, season_type FROM season_rows
        UNION
        SELECT player_id, season, season_type FROM starts
    ),
    lines AS (
        SELECT k.player_id, k.season, k.season_type,
               r.team_id, r.games, {stats},
               COALESCE(st.start_rows, 0) AS start_rows,
               COALESCE(st.wins, 0) AS wins,
               COALESCE(st.losses, 0) AS losses,
               COALESCE(st.ties, 0) AS ties
        FROM line_keys k
        LEFT JOIN season_rows r
          ON r.player_id = k.player_id AND r.season = k.season AND r.season_type = k.season_type
        LEFT JOIN starts st
          ON st.player_id = k.player_id AND st.season = k.season
         AND st.season_type = k.season_type
    )
    """


def totals_select(category: PlayerLeaderCategory = "passing") -> str:
    """The per-(player, season_type) aggregate over `lines`. `qualifies` is
    `category`'s leaderboard rule (`QUALIFYING`) holding on any line; the
    totals themselves are the same whatever the category. Each stat column
    combines by `stat_total`, so a career "long" is a MAX and everything
    else a null-aware SUM."""
    stats = ", ".join(f"{stat_total(c)} AS {c}" for c in STAT_COLUMNS)
    return f"""
    SELECT player_id, season_type,
           COUNT(*) AS seasons,
           MIN(season) AS first_season,
           MAX(season) AS last_season,
           {null_aware_sum("games")} AS games,
           SUM(wins) AS wins, SUM(losses) AS losses, SUM(ties) AS ties,
           {stats},
           MAX(CASE WHEN {QUALIFYING[category]} THEN 1 ELSE 0 END) AS qualifies
    FROM lines
    GROUP BY player_id, season_type
    """
