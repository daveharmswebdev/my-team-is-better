"""Career leaderboards (#296, #312, #314, #315): a stat column sorted descending, no rating math."""

from __future__ import annotations

import sqlite3
from typing import get_args

from cfb_strength.contracts import (
    PLAYER_LEADER_FG_PCT_MIN_ATTEMPTS,
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

# Fixed SQL only: a sort never reaches SQL as caller text. Each value is an
# expression over one career-totals row aliased `q`; a NULL in any input is a
# NULL sort value (unranked, last), never a 0.
_SORT_COLUMN: dict[PlayerLeaderSort, str] = {
    "passing_yards": "q.passing_yards",
    "passing_tds": "q.passing_tds",
    "wins": "q.wins",
    "rushing_yards": "q.rushing_yards",
    "rushing_tds": "q.rushing_tds",
    "carries": "q.carries",
    "receiving_yards": "q.receiving_yards",
    "receiving_tds": "q.receiving_tds",
    "receptions": "q.receptions",
    "fg_made": "q.fg_made",
    # The exact ratio, never rounded (#315). A float quotient is a faithful
    # ranking key for it: IEEE division is correctly rounded, so equal ratios
    # (9/10, 90/100) give the identical double and tie, and two different
    # ratios of attempt counts this size differ by at least 1/(a*b), far
    # above a double's resolution, so they never collapse into a tie.
    "fg_pct": "CAST(q.fg_made AS REAL) / q.fg_att",
    "fg_made_50_plus": "q.fg_made_50_59 + q.fg_made_60_",
    "fg_long": "q.fg_long",
    "fg_att": "q.fg_att",
    "pat_made": "q.pat_made",
    "pt_yards": "q.pt_yards",
    "pt_net_yards": "q.pt_net_yards",
    "pt_att": "q.pt_att",
    "pt_inside_20": "q.pt_inside_20",
}

# A sort's extra condition on who is on its board, over the career-totals row
# `t`, on top of the category's qualifying rule. Only `fg_pct` has one
# (`PLAYER_LEADER_FG_PCT_MIN_ATTEMPTS`): a kicker below the minimum is left
# off the board, so the page and `total` both drop him. A NULL attempts total
# cannot show the minimum is met, so it is off the board too.
_SORT_GATE: dict[PlayerLeaderSort, str] = {
    "fg_pct": "t.fg_att >= :fg_pct_min_attempts",
}


def _qualifying_cte(category: PlayerLeaderCategory, sort: PlayerLeaderSort) -> str:
    """`WITH ... qualifying AS (...)`: the one population both the page and
    the count read, `category`'s qualifying players in `:sport` and
    `:season_type`, narrowed by `sort`'s gate if it has one."""
    gate = _SORT_GATE.get(sort)
    where = "t.qualifies = 1" if gate is None else f"t.qualifies = 1 AND {gate}"
    return f"""
    {lines_cte(by_player=False, by_season_type=True)},
    totals AS ({totals_select(category)}),
    qualifying AS (
        SELECT t.*, p.display_name, p.position
        FROM totals t
        JOIN players p ON p.id = t.player_id AND p.sport = :sport
        WHERE {where}
    )
    """


def _leaders_sql(category: PlayerLeaderCategory, sort: PlayerLeaderSort) -> str:
    sort_column = _SORT_COLUMN[sort]
    stats = ", ".join(f"q.{c}" for c in STAT_COLUMNS)
    return f"""
    {_qualifying_cte(category, sort)},
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


def _count_sql(category: PlayerLeaderCategory, sort: PlayerLeaderSort) -> str:
    return f"""
    {_qualifying_cte(category, sort)}
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
    row with a carry; receiving, a season row with a target or a reception --
    so a player who was thrown to and caught nothing is on the board with 0
    receptions, and so are the 2003-2008 seasons nflverse publishes with no
    targets at all; kicking, a season row with a field-goal or PAT attempt;
    punting, a season row with a punt (`_sql.QUALIFYING`). The one exception
    is the `fg_pct` sort, whose board holds only kickers with at least
    PLAYER_LEADER_FG_PCT_MIN_ATTEMPTS[season_type] career attempts, and whose
    `total` counts only them. `sort=None` is the category's first sort in
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
    params = {
        "sport": sport,
        "season_type": season_type,
        "limit": limit,
        "offset": offset,
        "fg_pct_min_attempts": PLAYER_LEADER_FG_PCT_MIN_ATTEMPTS[season_type],
    }
    fetched = conn.execute(_leaders_sql(category, resolved), params).fetchall()
    if fetched:
        total = int(fetched[0]["total"])
    else:
        total = int(conn.execute(_count_sql(category, resolved), params).fetchone()[0])

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
