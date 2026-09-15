"""A player's career by season (#296), read from the player tables."""

from __future__ import annotations

import sqlite3
from typing import Any, cast

from cfb_strength.contracts import (
    PlayerCareer,
    PlayerCareerTotals,
    PlayerSeasonLine,
    PlayerSeasonType,
    PlayerStats,
    Sport,
    StarterRecord,
    UnknownPlayerError,
)
from cfb_strength.players._sql import STAT_COLUMNS, lines_cte, totals_select

_SEASON_TYPE_ORDER = {"regular": 0, "postseason": 1}

_LINES_SQL = f"""
{lines_cte(by_player=True, by_season_type=False)}
SELECT l.*, t.school AS fallback_school
FROM lines l
LEFT JOIN teams t ON t.id = l.team_id AND t.sport = :sport
"""

_TOTALS_SQL = f"""
{lines_cte(by_player=True, by_season_type=False)}
{totals_select()}
"""

# Every team the player has a stat line or a QB start for, one row per
# (season, season_type, team), in order of that team's first game.
_TEAMS_SQL = """
WITH appearances AS (
    SELECT game_id, team_id FROM player_game_stats
    WHERE player_id = :player_id AND sport = :sport
    UNION
    SELECT game_id, team_id FROM game_starters
    WHERE player_id = :player_id AND sport = :sport AND position = 'QB'
),
ordered AS (
    SELECT g.season, g.season_type, a.team_id, t.school,
           ROW_NUMBER() OVER (
               PARTITION BY g.season, g.season_type, a.team_id
               ORDER BY g.start_date, g.week, g.id
           ) AS nth,
           g.start_date, g.week, g.id AS game_id
    FROM appearances a
    JOIN games g ON g.id = a.game_id AND g.sport = :sport
    JOIN teams t ON t.id = a.team_id AND t.sport = :sport
)
SELECT season, season_type, team_id, school
FROM ordered
WHERE nth = 1
ORDER BY season, season_type, start_date, week, game_id
"""

# Completed games with no player_game_stats rows at all.
_UNLOGGED_GAMES_SQL = """
SELECT g.season, g.season_type, g.home_team_id, g.away_team_id
FROM games g
WHERE g.sport = :sport AND g.completed = 1
  AND NOT EXISTS (
      SELECT 1 FROM player_game_stats p WHERE p.game_id = g.id AND p.sport = :sport
  )
"""


def _stats(row: sqlite3.Row) -> PlayerStats:
    return PlayerStats(**{c: row[c] for c in STAT_COLUMNS})


def _record(row: sqlite3.Row) -> StarterRecord:
    return StarterRecord(wins=row["wins"], losses=row["losses"], ties=row["ties"])


def get_player_career(conn: sqlite3.Connection, *, sport: Sport, player_id: int) -> PlayerCareer:
    """Every season line of one player in `sport`, with regular-season and
    postseason totals. Raises UnknownPlayerError when no `players` row has
    that id and sport."""
    player = conn.execute(
        "SELECT display_name, position FROM players WHERE id = ? AND sport = ?",
        (player_id, sport),
    ).fetchone()
    if player is None:
        raise UnknownPlayerError(player_id, sport)
    params: dict[str, Any] = {"sport": sport, "player_id": player_id}

    teams: dict[tuple[int, str], list[tuple[int, str]]] = {}
    for r in conn.execute(_TEAMS_SQL, params).fetchall():
        teams.setdefault((r["season"], r["season_type"]), []).append((r["team_id"], r["school"]))

    unlogged: dict[tuple[int, str], list[tuple[int, int]]] = {}
    for r in conn.execute(_UNLOGGED_GAMES_SQL, params).fetchall():
        unlogged.setdefault((r["season"], r["season_type"]), []).append(
            (r["home_team_id"], r["away_team_id"])
        )

    line_rows = sorted(
        conn.execute(_LINES_SQL, params).fetchall(),
        key=lambda r: (r["season"], _SEASON_TYPE_ORDER[r["season_type"]]),
    )
    seasons: list[PlayerSeasonLine] = []
    for r in line_rows:
        key = (r["season"], r["season_type"])
        line_teams = teams.get(key)
        if line_teams is None:
            line_teams = (
                [] if r["fallback_school"] is None else [(r["team_id"], r["fallback_school"])]
            )
        team_ids = {team_id for team_id, _ in line_teams}
        seasons.append(
            PlayerSeasonLine(
                season=r["season"],
                season_type=cast(PlayerSeasonType, r["season_type"]),
                teams=[school for _, school in line_teams],
                games=r["games"],
                record=_record(r),
                stats=_stats(r),
                games_without_stat_lines=sum(
                    1
                    for home, away in unlogged.get(key, [])
                    if home in team_ids or away in team_ids
                ),
            )
        )

    totals = {
        r["season_type"]: PlayerCareerTotals(
            season_type=cast(PlayerSeasonType, r["season_type"]),
            seasons=r["seasons"],
            games=r["games"],
            record=_record(r),
            stats=_stats(r),
        )
        for r in conn.execute(_TOTALS_SQL, params).fetchall()
    }
    return PlayerCareer(
        sport=sport,
        player_id=player_id,
        display_name=player["display_name"],
        position=player["position"],
        seasons=seasons,
        regular_season=totals.get("regular"),
        postseason=totals.get("postseason"),
    )
