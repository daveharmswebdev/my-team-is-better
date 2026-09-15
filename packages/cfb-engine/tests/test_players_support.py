"""A small synthetic player db for the `cfb_strength.players` tests (#296).

No tests live here: `test_players_leaders.py` and `test_players_career.py`
import `PlayerDb` to build a real current-schema sqlite db (`ensure_schema`)
row by row, so every case states exactly the rows it depends on.
"""

from __future__ import annotations

import itertools
import json
import sqlite3
from pathlib import Path

from cfb_strength.contracts import PlayerStats
from cfb_strength.db.connection import ensure_schema, get_conn

STAT_COLUMNS = tuple(PlayerStats.__dataclass_fields__)


class PlayerDb:
    """Row builders over one connection. Ids come from one counter per table,
    so an id is unique across sports exactly as the real surrogate ids are."""

    def __init__(self, path: Path, sport: str = "nfl") -> None:
        self.conn = get_conn(path)
        ensure_schema(self.conn)
        self.sport = sport
        self._ids = itertools.count(1)

    def close(self) -> None:
        self.conn.close()

    def team(self, school: str, *, sport: str | None = None) -> int:
        team_id = next(self._ids)
        self.conn.execute(
            "INSERT INTO teams (id, school, sport) VALUES (?, ?, ?)",
            (team_id, school, sport or self.sport),
        )
        return team_id

    def player(
        self,
        name: str,
        *,
        position: str | None = "QB",
        sport: str | None = None,
        player_id: int | None = None,
    ) -> int:
        pid = player_id if player_id is not None else next(self._ids)
        self.conn.execute(
            "INSERT INTO players (id, sport, display_name, position) VALUES (?, ?, ?, ?)",
            (pid, sport or self.sport, name, position),
        )
        return pid

    def game(
        self,
        season: int,
        home: int,
        away: int,
        home_points: int | None,
        away_points: int | None,
        *,
        season_type: str = "regular",
        week: int = 1,
        start_date: str | None = None,
        completed: bool = True,
        sport: str | None = None,
    ) -> int:
        game_id = next(self._ids)
        self.conn.execute(
            """
            INSERT INTO games (id, season, week, season_type, start_date, completed,
                               home_team_id, away_team_id, home_team, away_team,
                               home_points, away_points, raw_json, sport, source_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'home', 'away', ?, ?, ?, ?, ?)
            """,
            (
                game_id,
                season,
                week,
                season_type,
                start_date or f"{season}-09-{week:02d}",
                int(completed),
                home,
                away,
                home_points,
                away_points,
                json.dumps({}),
                sport or self.sport,
                f"g{game_id}",
            ),
        )
        return game_id

    def start(self, game: int, team: int, player: int, *, sport: str | None = None) -> None:
        self.conn.execute(
            "INSERT INTO game_starters (game_id, team_id, position, player_id, sport, source) "
            "VALUES (?, ?, 'QB', ?, ?, 'test')",
            (game, team, player, sport or self.sport),
        )

    def game_line(
        self, player: int, game: int, team: int, *, sport: str | None = None, **stats: int | None
    ) -> None:
        values = [stats.get(c) for c in STAT_COLUMNS]
        self.conn.execute(
            f"INSERT INTO player_game_stats (player_id, game_id, team_id, sport, "
            f"{', '.join(STAT_COLUMNS)}) VALUES (?, ?, ?, ?, {', '.join('?' * len(STAT_COLUMNS))})",
            (player, game, team, sport or self.sport, *values),
        )

    def season(
        self,
        player: int,
        season: int,
        *,
        season_type: str = "regular",
        team: int | None = None,
        games: int | None = 1,
        sport: str | None = None,
        **stats: int | None,
    ) -> None:
        values = [stats.get(c) for c in STAT_COLUMNS]
        self.conn.execute(
            f"INSERT INTO player_season_stats (player_id, season, season_type, team_id, games, "
            f"source, sport, {', '.join(STAT_COLUMNS)}) "
            f"VALUES (?, ?, ?, ?, ?, 'test', ?, {', '.join('?' * len(STAT_COLUMNS))})",
            (player, season, season_type, team, games, sport or self.sport, *values),
        )


def full_stats(**overrides: int | None) -> dict[str, int | None]:
    """Every stat column set (to 1 unless overridden), so a total is only None
    when a test means it to be."""
    stats: dict[str, int | None] = dict.fromkeys(STAT_COLUMNS, 1)
    stats.update(overrides)
    return stats


def conn_of(db: PlayerDb) -> sqlite3.Connection:
    db.conn.commit()
    return db.conn
