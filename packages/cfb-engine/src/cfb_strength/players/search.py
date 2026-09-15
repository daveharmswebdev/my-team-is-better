"""Player search by name (#301), among players who qualify for a leaderboard."""

from __future__ import annotations

import sqlite3

from cfb_strength.contracts import (
    PLAYER_SEARCH_MAX_LIMIT,
    PLAYER_SEARCH_MIN_QUERY_LENGTH,
    PlayerSearch,
    PlayerSearchRow,
    Sport,
)
from cfb_strength.players._sql import lines_cte, totals_select

# The same per-(player, season_type) totals a leaderboard ranks, folded to one
# row per player: qualifying in either season type, the season span across
# both, and regular-season career passing yards for the order (None when that
# total is None or the player has no regular-season line).
#
# The caller's text reaches SQLite only as the bound `:pattern`, with LIKE's
# wildcards and the escape character escaped, so `%` and `_` match themselves.
_SEARCH_SQL = f"""
{lines_cte(by_player=False, by_season_type=False)},
totals AS ({totals_select()})
SELECT p.id AS player_id, p.display_name, p.position,
       MIN(t.first_season) AS first_season,
       MAX(t.last_season) AS last_season,
       MAX(CASE WHEN t.season_type = 'regular' THEN t.passing_yards END) AS regular_yards
FROM totals t
JOIN players p ON p.id = t.player_id AND p.sport = :sport
WHERE lower(p.display_name) LIKE lower(:pattern) ESCAPE '\\'
GROUP BY p.id, p.display_name, p.position
HAVING MAX(t.qualifies) = 1
ORDER BY regular_yards DESC NULLS LAST, p.display_name, p.id
LIMIT :limit
"""


def _like_substring(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def search_players(
    conn: sqlite3.Connection, *, sport: Sport, query: str, limit: int = 10
) -> PlayerSearch:
    """Qualifying players in `sport` whose `display_name` contains the
    stripped `query`, case-insensitively. Ordered by regular-season career
    passing yards descending (None last), then `display_name`, then
    `player_id`.

    Raises ValueError unless 1 <= limit <= PLAYER_SEARCH_MAX_LIMIT and the
    stripped query has at least PLAYER_SEARCH_MIN_QUERY_LENGTH characters."""
    if not 1 <= limit <= PLAYER_SEARCH_MAX_LIMIT:
        raise ValueError(f"limit must be between 1 and {PLAYER_SEARCH_MAX_LIMIT}, got {limit}")
    stripped = query.strip()
    if len(stripped) < PLAYER_SEARCH_MIN_QUERY_LENGTH:
        raise ValueError(
            f"query must have at least {PLAYER_SEARCH_MIN_QUERY_LENGTH} characters, "
            f"got {stripped!r}"
        )
    if "\x00" in stripped:
        # SQLite's LIKE stops reading its pattern at a NUL, which would widen the
        # match; no name contains one, so the literal answer is no rows (#301 review).
        return PlayerSearch(sport=sport, query=stripped, limit=limit, rows=[])
    params = {"sport": sport, "pattern": _like_substring(stripped), "limit": limit}
    rows = [
        PlayerSearchRow(
            player_id=r["player_id"],
            display_name=r["display_name"],
            position=r["position"],
            first_season=r["first_season"],
            last_season=r["last_season"],
        )
        for r in conn.execute(_SEARCH_SQL, params).fetchall()
    ]
    return PlayerSearch(sport=sport, query=stripped, limit=limit, rows=rows)
