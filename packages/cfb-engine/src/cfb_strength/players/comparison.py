"""Two players side by side (#301): both careers, and the games they started
against each other at QB. No rating math: nothing here compares `a`'s numbers
with `b`'s."""

from __future__ import annotations

import sqlite3
from typing import Any, cast

from cfb_strength.contracts import (
    PlayerComparison,
    PlayerHeadToHead,
    PlayerHeadToHeadGame,
    PlayerSeasonType,
    PlayerStats,
    Sport,
    StarterRecord,
)
from cfb_strength.players._sql import _COUNTED, STAT_COLUMNS
from cfb_strength.players.career import get_player_career

# One row per game in which `a` and `b` are both listed QB starters
# (`game_starters`), for different teams, in a game the career W-L-T counts
# (`_COUNTED`, shared with the career query so the two can't drift apart). A
# reliever has a stat line but no starter row, so relief never qualifies.
# `a_row`/`b_row` tell a missing stat line (NULL) from a line of NULL stats.
_HEAD_TO_HEAD_SQL = f"""
SELECT g.id AS game_id, g.season, g.season_type, g.week, g.start_date, g.source_id,
       ta.school AS a_team, tb.school AS b_team,
       CASE WHEN sa.team_id = g.home_team_id THEN g.home_points ELSE g.away_points END
           AS a_points,
       CASE WHEN sb.team_id = g.home_team_id THEN g.home_points ELSE g.away_points END
           AS b_points,
       pa.player_id AS a_row, {", ".join(f"pa.{c} AS a_{c}" for c in STAT_COLUMNS)},
       pb.player_id AS b_row, {", ".join(f"pb.{c} AS b_{c}" for c in STAT_COLUMNS)}
FROM game_starters sa
JOIN game_starters sb
  ON sb.game_id = sa.game_id AND sb.team_id <> sa.team_id
 AND sb.player_id = :b AND sb.position = 'QB' AND sb.sport = :sport
JOIN games g ON g.id = sa.game_id AND g.sport = :sport
JOIN teams ta ON ta.id = sa.team_id AND ta.sport = :sport
JOIN teams tb ON tb.id = sb.team_id AND tb.sport = :sport
LEFT JOIN player_game_stats pa
  ON pa.game_id = g.id AND pa.player_id = :a AND pa.sport = :sport
LEFT JOIN player_game_stats pb
  ON pb.game_id = g.id AND pb.player_id = :b AND pb.sport = :sport
WHERE sa.player_id = :a AND sa.position = 'QB' AND sa.sport = :sport
  AND g.season_type IN ('regular', 'postseason')
  AND {_COUNTED}
ORDER BY g.start_date, g.week, g.id
"""


def _side_stats(row: sqlite3.Row, side: str) -> PlayerStats | None:
    if row[f"{side}_row"] is None:
        return None
    return PlayerStats(**{c: row[f"{side}_{c}"] for c in STAT_COLUMNS})


def _head_to_head(
    season_type: PlayerSeasonType, games: list[PlayerHeadToHeadGame]
) -> PlayerHeadToHead:
    return PlayerHeadToHead(
        season_type=season_type,
        record=StarterRecord(
            wins=sum(1 for g in games if g.a_points > g.b_points),
            losses=sum(1 for g in games if g.a_points < g.b_points),
            ties=sum(1 for g in games if g.a_points == g.b_points),
        ),
        games=games,
    )


def get_player_comparison(
    conn: sqlite3.Connection, *, sport: Sport, a: int, b: int
) -> PlayerComparison:
    """`a`'s and `b`'s careers (exactly `get_player_career`) and `a`'s record
    in the games the two started against each other, by season type.

    Raises ValueError when a == b, and UnknownPlayerError for the first of
    `a`, `b` with no `players` row in `sport`."""
    if a == b:
        raise ValueError(f"cannot compare player {a} with himself")
    career_a = get_player_career(conn, sport=sport, player_id=a)
    career_b = get_player_career(conn, sport=sport, player_id=b)

    params: dict[str, Any] = {"sport": sport, "a": a, "b": b}
    by_type: dict[str, list[PlayerHeadToHeadGame]] = {"regular": [], "postseason": []}
    for r in conn.execute(_HEAD_TO_HEAD_SQL, params).fetchall():
        by_type[r["season_type"]].append(
            PlayerHeadToHeadGame(
                season=r["season"],
                season_type=cast(PlayerSeasonType, r["season_type"]),
                week=r["week"],
                start_date=r["start_date"],
                source_id=r["source_id"],
                a_team=r["a_team"],
                b_team=r["b_team"],
                a_points=r["a_points"],
                b_points=r["b_points"],
                a_stats=_side_stats(r, "a"),
                b_stats=_side_stats(r, "b"),
            )
        )
    return PlayerComparison(
        sport=sport,
        a=career_a,
        b=career_b,
        regular_season_head_to_head=_head_to_head("regular", by_type["regular"]),
        postseason_head_to_head=_head_to_head("postseason", by_type["postseason"]),
    )
