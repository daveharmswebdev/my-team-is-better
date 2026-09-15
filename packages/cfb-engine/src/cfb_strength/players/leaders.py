"""Career leaderboards (#296, #312): a stat column sorted descending, no rating math."""

from __future__ import annotations

import sqlite3
from typing import get_args

from cfb_strength.contracts import (
    PLAYER_LEADER_SORTS_BY_CATEGORY,
    PLAYER_LEADERS_MAX_LIMIT,
    PlayerLeaderCategory,
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
_SORT_COLUMN: dict[PlayerLeaderSort, str] = {
    "passing_yards": "q.passing_yards",
    "passing_tds": "q.passing_tds",
    "wins": "q.wins",
    "rushing_yards": "q.rushing_yards",
    "rushing_tds": "q.rushing_tds",
    "carries": "q.carries",
}


def _qualifying_cte(category: PlayerLeaderCategory) -> str:
    """`WITH ... qualifying AS (...)`: the one population both the page and
    the count read, `category`'s qualifying players in `:sport` and
    `:season_type`."""
    return f"""
    {lines_cte(by_player=False, by_season_type=True)},
    totals AS ({totals_select(category)}),
    qualifying AS (
        SELECT t.*, p.display_name, p.position
        FROM totals t
        JOIN players p ON p.id = t.player_id AND p.sport = :sport
        WHERE t.qualifies = 1
    )
    """


def _leaders_sql(category: PlayerLeaderCategory, sort_column: str) -> str:
    stats = ", ".join(f"q.{c}" for c in STAT_COLUMNS)
    return f"""
    {_qualifying_cte(category)},
    ranked AS (
        SELECT q.player_id, q.display_name, q.position,
               q.first_season, q.last_season, q.games, q.wins, q.losses, q.ties, {stats},
               {sort_column} AS sort_value,
               CASE WHEN {sort_column} IS NULL THEN NULL
                    ELSE RANK() OVER (ORDER BY {sort_column} DESC NULLS LAST) END AS rank
        FROM qualifying q
    )
    SELECT *, COUNT(*) OVER () AS total
    FROM ranked
    ORDER BY sort_value DESC NULLS LAST, display_name, player_id
    LIMIT :limit OFFSET :offset
    """


def _count_sql(category: PlayerLeaderCategory) -> str:
    return f"""
    {_qualifying_cte(category)}
    SELECT COUNT(*) FROM qualifying
    """


def get_player_leaders(
    conn: sqlite3.Connection,
    *,
    sport: Sport,
    category: PlayerLeaderCategory = "passing",
    season_type: PlayerSeasonType = "regular",
    sort: PlayerLeaderSort | None = None,
    limit: int = 50,
    offset: int = 0,
) -> PlayerLeaders:
    """One page of `category`'s career leaderboard for `sport` and `season_type`.

    Qualifies, per season type with no minimum and whatever the position:
    passing, a season row with a pass attempt or a QB start; rushing, a season
    row with a carry. `sort=None` is the category's first sort in
    PLAYER_LEADER_SORTS_BY_CATEGORY, and the response echoes the resolved one.
    `rank` is competition ranking over the whole qualifying population; a None
    sort value is unranked and sorts last. Raises ValueError unless
    1 <= limit <= PLAYER_LEADERS_MAX_LIMIT, offset >= 0, and `sort` is one of
    `category`'s sorts."""
    if not 1 <= limit <= PLAYER_LEADERS_MAX_LIMIT:
        raise ValueError(f"limit must be between 1 and {PLAYER_LEADERS_MAX_LIMIT}, got {limit}")
    if offset < 0:
        raise ValueError(f"offset must be >= 0, got {offset}")
    if season_type not in get_args(PlayerSeasonType):
        raise ValueError(f"unknown season_type {season_type!r}")
    sorts = PLAYER_LEADER_SORTS_BY_CATEGORY.get(category)
    if sorts is None:
        raise ValueError(f"unknown category {category!r}")
    resolved = sorts[0] if sort is None else sort
    if resolved not in sorts:
        raise ValueError(f"sort {sort!r} is not a {category} sort; expected one of {sorts}")
    sort_column = _SORT_COLUMN[resolved]

    params = {"sport": sport, "season_type": season_type, "limit": limit, "offset": offset}
    fetched = conn.execute(_leaders_sql(category, sort_column), params).fetchall()
    if fetched:
        total = int(fetched[0]["total"])
    else:
        total = int(conn.execute(_count_sql(category), params).fetchone()[0])

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
        category=category,
        season_type=season_type,
        sort=resolved,
        limit=limit,
        offset=offset,
        total=total,
        rows=rows,
    )
