"""How much of a player's career the db holds (#446, epic #443).

One reading of `contracts.PlayerCoverage` shared by careers, leaders rows and
search rows, so the three can't disagree for one player:

  * the data span is the db's MIN/MAX regular season in `player_season_stats`
    for the sport -- one aggregate per call, never a constant;
  * the covered span is the player's own lines in either season type: the
    seasons with a season row or a QB `game_starters` start, the same seasons
    a `PlayerSeasonLine` exists for (`_sql.lines_cte`);
  * the career span is the source's `players.career_first_season` /
    `career_last_season` (#444), None when the source doesn't say.

Every query is scoped by `:sport`; player ids reach SQLite as one bound JSON
array, so a page of rows is one grouped query, not one per row.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable

from cfb_strength.contracts import PlayerCoverage, Sport

_DATA_SPAN_SQL = """
SELECT MIN(season), MAX(season) FROM player_season_stats
WHERE sport = :sport AND season_type = 'regular'
"""

# One row per requested player in `:sport`. The season-row and start halves
# mirror `_sql.lines_cte(by_season_type=False)`'s line keys, folded to seasons.
_COVERED_SQL = """
WITH ids AS (SELECT DISTINCT value AS id FROM json_each(:ids)),
covered AS (
    SELECT player_id, season FROM player_season_stats
    WHERE sport = :sport AND player_id IN (SELECT id FROM ids)
    UNION
    SELECT s.player_id, g.season
    FROM game_starters s
    JOIN games g ON g.id = s.game_id
    WHERE s.sport = :sport AND g.sport = :sport AND s.position = 'QB'
      AND g.season_type IN ('regular', 'postseason')
      AND s.player_id IN (SELECT id FROM ids)
)
SELECT p.id, p.career_first_season, p.career_last_season,
       MIN(c.season) AS covered_first, MAX(c.season) AS covered_last,
       COUNT(c.season) AS covered_seasons
FROM players p
LEFT JOIN covered c ON c.player_id = p.id
WHERE p.sport = :sport AND p.id IN (SELECT id FROM ids)
GROUP BY p.id, p.career_first_season, p.career_last_season
"""


def data_span(conn: sqlite3.Connection, *, sport: Sport) -> tuple[int | None, int | None]:
    """The db's player-stat span for `sport`: (None, None) with no
    regular-season rows."""
    first, last = conn.execute(_DATA_SPAN_SQL, {"sport": sport}).fetchone()
    return first, last


def coverages(
    conn: sqlite3.Connection,
    *,
    sport: Sport,
    player_ids: Iterable[int],
    span: tuple[int | None, int | None] | None = None,
) -> dict[int, PlayerCoverage]:
    """Each requested player's coverage, keyed by id; an id with no
    `players` row in `sport` is absent. `span` is `data_span`'s result when
    the caller already read it, so a call reads it once."""
    ids = sorted(set(player_ids))
    if not ids:
        return {}
    data_first, data_last = data_span(conn, sport=sport) if span is None else span
    rows = conn.execute(_COVERED_SQL, {"sport": sport, "ids": json.dumps(ids)}).fetchall()
    return {
        int(r[0]): PlayerCoverage(
            career_first_season=r[1],
            career_last_season=r[2],
            data_first_season=data_first,
            data_last_season=data_last,
            covered_first_season=r[3],
            covered_last_season=r[4],
            covered_seasons=int(r[5]),
        )
        for r in rows
    }


def coverage(conn: sqlite3.Connection, *, sport: Sport, player_id: int) -> PlayerCoverage:
    """One player's coverage. The player must exist in `sport`."""
    return coverages(conn, sport=sport, player_ids=[player_id])[player_id]
