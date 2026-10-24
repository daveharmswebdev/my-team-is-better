"""Player search by name (#301), among players on any leaderboard (#371)."""

from __future__ import annotations

import sqlite3
from typing import get_args

from cfb_strength.contracts import (
    PLAYER_SEARCH_MAX_LIMIT,
    PLAYER_SEARCH_MIN_QUERY_LENGTH,
    POSITION_GROUP_BY_LABEL,
    PlayerPositionGroup,
    PlayerSearch,
    PlayerSearchRow,
    Sport,
)
from cfb_strength.players._sql import any_category_totals_select, lines_cte

# The same per-(player, season_type) totals a leaderboard ranks, folded to one
# row per player: qualifying for any leaderboard category in either season
# type (#371), the season span across both, and regular-season career games
# for the order (None when that total is None or the player has no
# regular-season line). Only the players whose name matches are aggregated at
# all (#368); the WHERE below restates the match on the joined row.
#
# The caller's text reaches SQLite only as the bound `:pattern`, with LIKE's
# wildcards and the escape character escaped, so `%` and `_` match themselves.
#
# A position group (#428) adds `{group_filter}`: `p.position` in the labels
# `POSITION_GROUP_BY_LABEL` maps to it, each bound as a parameter. It sits in
# the WHERE, so it narrows the rows before `LIMIT` takes its page.
_SEARCH_SQL_TEMPLATE = f"""
{lines_cte(by_player=False, by_season_type=False, by_name=True)},
totals AS ({any_category_totals_select()})
SELECT p.id AS player_id, p.display_name, p.position,
       MIN(t.first_season) AS first_season,
       MAX(t.last_season) AS last_season,
       MAX(CASE WHEN t.season_type = 'regular' THEN t.games END) AS regular_games
FROM totals t
JOIN players p ON p.id = t.player_id AND p.sport = :sport
WHERE lower(p.display_name) LIKE lower(:pattern) ESCAPE '\\'{{group_filter}}
GROUP BY p.id, p.display_name, p.position
HAVING MAX(t.qualifies) = 1
ORDER BY regular_games DESC NULLS LAST, p.display_name, p.id
LIMIT :limit
"""

_SEARCH_SQL = _SEARCH_SQL_TEMPLATE.format(group_filter="")

_GROUPS: frozenset[str] = frozenset(get_args(PlayerPositionGroup))


def _group_labels(group: PlayerPositionGroup) -> list[str]:
    """The `players.position` labels in `group`, from the contract's mapping."""
    return sorted(label for label, g in POSITION_GROUP_BY_LABEL.items() if g == group)


def _group_query(group: PlayerPositionGroup) -> tuple[str, dict[str, str]]:
    """The group's SQL filter and its bound labels (`:group_label_<i>`)."""
    params = {f"group_label_{i}": label for i, label in enumerate(_group_labels(group))}
    placeholders = ", ".join(f":{name}" for name in params)
    return f" AND p.position IN ({placeholders})", params


def _like_substring(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def search_players(
    conn: sqlite3.Connection,
    *,
    sport: Sport,
    query: str,
    limit: int = 10,
    group: PlayerPositionGroup | None = None,
) -> PlayerSearch:
    """Players in `sport` on any leaderboard (`_sql.QUALIFYING`, either
    season type) whose `display_name` contains the stripped `query`,
    case-insensitively. Ordered by regular-season career games descending
    (None last), then `display_name`, then `player_id` (#371).

    With a `group` (#428), only players whose `position` maps to it under
    `POSITION_GROUP_BY_LABEL`, filtered before `limit`; None is unfiltered.

    Raises ValueError unless 1 <= limit <= PLAYER_SEARCH_MAX_LIMIT, the
    stripped query has at least PLAYER_SEARCH_MIN_QUERY_LENGTH characters, and
    `group` is None or a `PlayerPositionGroup`."""
    if not 1 <= limit <= PLAYER_SEARCH_MAX_LIMIT:
        raise ValueError(f"limit must be between 1 and {PLAYER_SEARCH_MAX_LIMIT}, got {limit}")
    stripped = query.strip()
    if len(stripped) < PLAYER_SEARCH_MIN_QUERY_LENGTH:
        raise ValueError(
            f"query must have at least {PLAYER_SEARCH_MIN_QUERY_LENGTH} characters, "
            f"got {stripped!r}"
        )
    if group is not None and group not in _GROUPS:
        raise ValueError(f"group must be one of {sorted(_GROUPS)} or None, got {group!r}")
    if "\x00" in stripped:
        # SQLite's LIKE stops reading its pattern at a NUL, which would widen the
        # match; no name contains one, so the literal answer is no rows (#301 review).
        return PlayerSearch(sport=sport, query=stripped, limit=limit, rows=[])
    params: dict[str, str | int] = {
        "sport": sport,
        "pattern": _like_substring(stripped),
        "limit": limit,
    }
    sql = _SEARCH_SQL
    if group is not None:
        group_filter, group_params = _group_query(group)
        sql = _SEARCH_SQL_TEMPLATE.format(group_filter=group_filter)
        params.update(group_params)
    rows = [
        PlayerSearchRow(
            player_id=r["player_id"],
            display_name=r["display_name"],
            position=r["position"],
            first_season=r["first_season"],
            last_season=r["last_season"],
        )
        for r in conn.execute(sql, params).fetchall()
    ]
    return PlayerSearch(sport=sport, query=stripped, limit=limit, rows=rows)
