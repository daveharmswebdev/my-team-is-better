"""Career leaderboards (#296): a stat column sorted descending, no rating math."""

from __future__ import annotations

import sqlite3
from typing import get_args

from cfb_strength.contracts import (
    PLAYER_LEADERS_MAX_LIMIT,
    PlayerLeaderRow,
    PlayerLeaders,
    PlayerLeaderSort,
    PlayerSeasonType,
    PlayerStats,
    Sport,
    StarterRecord,
)
from cfb_strength.players._sql import STAT_COLUMNS, lines_cte, totals_select

# Fixed column names only: a sort never reaches SQL as caller text.
_SORT_COLUMN: dict[str, str] = {
    "passing_yards": "t.passing_yards",
    "passing_tds": "t.passing_tds",
    "wins": "t.wins",
}


def _leaders_sql(sort_column: str) -> str:
    stats = ", ".join(f"t.{c}" for c in STAT_COLUMNS)
    return f"""
    {lines_cte(by_player=False, by_season_type=True)},
    totals AS ({totals_select()}),
    ranked AS (
        SELECT t.player_id, p.display_name, p.position,
               t.first_season, t.last_season, t.games, t.wins, t.losses, t.ties, {stats},
               {sort_column} AS sort_value,
               CASE WHEN {sort_column} IS NULL THEN NULL
                    ELSE RANK() OVER (ORDER BY {sort_column} DESC NULLS LAST) END AS rank
        FROM totals t
        JOIN players p ON p.id = t.player_id AND p.sport = :sport
        WHERE t.qualifies = 1
    )
    SELECT *, COUNT(*) OVER () AS total
    FROM ranked
    ORDER BY sort_value DESC NULLS LAST, display_name, player_id
    LIMIT :limit OFFSET :offset
    """


def _count_sql() -> str:
    return f"""
    {lines_cte(by_player=False, by_season_type=True)},
    totals AS ({totals_select()})
    SELECT COUNT(*)
    FROM totals t
    JOIN players p ON p.id = t.player_id AND p.sport = :sport
    WHERE t.qualifies = 1
    """


def get_player_leaders(
    conn: sqlite3.Connection,
    *,
    sport: Sport,
    season_type: PlayerSeasonType = "regular",
    sort: PlayerLeaderSort = "passing_yards",
    limit: int = 50,
    offset: int = 0,
) -> PlayerLeaders:
    """One page of a career leaderboard for `sport` and `season_type`.

    Qualifies: a season row with at least one pass attempt, or one QB start,
    in that season type. `rank` is competition ranking over the whole
    qualifying population; a None sort value is unranked and sorts last.
    Raises ValueError unless 1 <= limit <= PLAYER_LEADERS_MAX_LIMIT and
    offset >= 0."""
    if not 1 <= limit <= PLAYER_LEADERS_MAX_LIMIT:
        raise ValueError(f"limit must be between 1 and {PLAYER_LEADERS_MAX_LIMIT}, got {limit}")
    if offset < 0:
        raise ValueError(f"offset must be >= 0, got {offset}")
    if season_type not in get_args(PlayerSeasonType):
        raise ValueError(f"unknown season_type {season_type!r}")
    sort_column = _SORT_COLUMN.get(sort)
    if sort_column is None:
        raise ValueError(f"unknown sort {sort!r}")

    params = {"sport": sport, "season_type": season_type, "limit": limit, "offset": offset}
    fetched = conn.execute(_leaders_sql(sort_column), params).fetchall()
    if fetched:
        total = int(fetched[0]["total"])
    else:
        total = int(conn.execute(_count_sql(), params).fetchone()[0])

    rows = [
        PlayerLeaderRow(
            rank=r["rank"],
            player_id=r["player_id"],
            display_name=r["display_name"],
            position=r["position"],
            first_season=r["first_season"],
            last_season=r["last_season"],
            games=r["games"],
            record=StarterRecord(wins=r["wins"], losses=r["losses"], ties=r["ties"]),
            stats=PlayerStats(**{c: r[c] for c in STAT_COLUMNS}),
        )
        for r in fetched
    ]
    return PlayerLeaders(
        sport=sport,
        season_type=season_type,
        sort=sort,
        limit=limit,
        offset=offset,
        total=total,
        rows=rows,
    )
