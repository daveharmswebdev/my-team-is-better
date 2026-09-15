"""Issue #289 (epic #288): the player tables and their row contracts.

The tables are new, so schema.sql's `CREATE TABLE IF NOT EXISTS` creates them
on a fresh db and on a pre-existing one alike; no ALTER TABLE migration is
needed. These tests pin the shape the ingest writes to and the readers of
steps 2-4 will query: the keys that stop a season being counted twice, the
closed season-type vocabulary, and the one list of stat columns shared by
`contracts.PlayerStats` and both stat tables.
"""

from __future__ import annotations

import dataclasses
import sqlite3
from pathlib import Path

import pytest

from cfb_strength.contracts import (
    GameStarterRow,
    PlayerGameStatRow,
    PlayerRow,
    PlayerSeasonStatRow,
    PlayerSourceIdRow,
    PlayerStats,
)
from cfb_strength.db.connection import ensure_schema, get_conn

PLAYER_TABLES = (
    "players",
    "player_source_ids",
    "game_starters",
    "player_game_stats",
    "player_season_stats",
    "player_game_feats",
)


@pytest.fixture
def conn(tmp_path: Path):
    c = get_conn(tmp_path / "players.sqlite3")
    ensure_schema(c)
    try:
        yield c
    finally:
        c.close()


def _columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [row["name"] for row in conn.execute(f"PRAGMA table_info({table})")]


def _primary_key(conn: sqlite3.Connection, table: str) -> list[str]:
    rows = [row for row in conn.execute(f"PRAGMA table_info({table})") if row["pk"]]
    return [row["name"] for row in sorted(rows, key=lambda r: r["pk"])]


def _seed_game(conn: sqlite3.Connection) -> None:
    conn.execute(
        "INSERT INTO teams (id, school, sport) VALUES (1, 'Home', 'nfl'), (2, 'Away', 'nfl')"
    )
    conn.execute(
        "INSERT INTO games (id, season, season_type, home_team_id, away_team_id, home_team, "
        "away_team, raw_json, sport) "
        "VALUES (10, 2008, 'regular', 1, 2, 'Home', 'Away', '{}', 'nfl')"
    )
    conn.execute("INSERT INTO players (id, sport, display_name) VALUES (100, 'nfl', 'A Passer')")


def test_fresh_db_has_every_player_table(conn: sqlite3.Connection) -> None:
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert set(PLAYER_TABLES) <= tables


def test_player_tables_carry_sport(conn: sqlite3.Connection) -> None:
    for table in (
        "players",
        "game_starters",
        "player_game_stats",
        "player_season_stats",
        "player_game_feats",
    ):
        assert "sport" in _columns(conn, table), table


def test_primary_keys(conn: sqlite3.Connection) -> None:
    assert _primary_key(conn, "players") == ["id"]
    assert _primary_key(conn, "player_source_ids") == ["source", "source_id"]
    assert _primary_key(conn, "game_starters") == ["game_id", "team_id", "position"]
    assert _primary_key(conn, "player_game_stats") == ["player_id", "game_id"]
    # Not keyed on `source`: one authoritative row per player-season, so a
    # second source for the same season can never double a career total.
    assert _primary_key(conn, "player_season_stats") == ["player_id", "season", "season_type"]
    assert _primary_key(conn, "player_game_feats") == [
        "player_id",
        "game_id",
        "kind",
        "definition_version",
    ]


def test_both_stat_tables_hold_exactly_the_contract_stat_columns(conn: sqlite3.Connection) -> None:
    stat_fields = [f.name for f in dataclasses.fields(PlayerStats)]
    for table in ("player_game_stats", "player_season_stats"):
        columns = _columns(conn, table)
        assert columns[-len(stat_fields) :] == stat_fields, table


def test_a_second_source_for_the_same_player_season_is_rejected(conn: sqlite3.Connection) -> None:
    _seed_game(conn)
    insert = (
        "INSERT INTO player_season_stats (player_id, season, season_type, sport, source) "
        "VALUES (100, 2008, 'regular', 'nfl', ?)"
    )
    conn.execute(insert, ("nflverse",))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(insert, ("pfr",))


def test_season_type_is_a_closed_vocabulary_in_the_db(conn: sqlite3.Connection) -> None:
    _seed_game(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO player_season_stats (player_id, season, season_type, sport, source) "
            "VALUES (100, 2008, 'REG', 'nfl', 'nflverse')"
        )


def test_a_starter_must_reference_a_known_player(conn: sqlite3.Connection) -> None:
    _seed_game(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO game_starters (game_id, team_id, position, player_id, sport, source) "
            "VALUES (10, 1, 'QB', 999, 'nfl', 'nflverse_schedule')"
        )


def test_untracked_stats_are_null_not_zero(conn: sqlite3.Connection) -> None:
    _seed_game(conn)
    conn.execute(
        "INSERT INTO player_game_stats (player_id, game_id, team_id, sport) "
        "VALUES (100, 10, 1, 'nfl')"
    )
    row = conn.execute("SELECT passing_yards, carries FROM player_game_stats").fetchone()
    assert (row["passing_yards"], row["carries"]) == (None, None)


@pytest.mark.filterwarnings("ignore::cfb_strength.db.connection.StaleDatabaseWarning")
def test_a_pre_existing_db_gains_the_player_tables_and_keeps_its_rows(tmp_path: Path) -> None:
    path = tmp_path / "pre_289.sqlite3"
    c = get_conn(path)
    ensure_schema(c)
    for table in reversed(PLAYER_TABLES):
        c.execute(f"DROP TABLE {table}")
    c.execute("INSERT INTO teams (id, school, sport) VALUES (1, 'Keep Me', 'nfl')")
    c.commit()
    c.close()

    c = get_conn(path)
    ensure_schema(c)
    tables = {row[0] for row in c.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert set(PLAYER_TABLES) <= tables
    assert c.execute("SELECT school FROM teams WHERE id = 1").fetchone()[0] == "Keep Me"
    c.close()


def test_player_rows_reject_an_unknown_sport() -> None:
    with pytest.raises(ValueError, match="sport"):
        PlayerRow(id=1, display_name="X", position="QB", birth_date=None, sport="xfl")  # type: ignore[arg-type]  # the runtime check is what's under test
    with pytest.raises(ValueError, match="sport"):
        GameStarterRow(game_id=1, team_id=1, position="QB", player_id=1, source="s", sport="xfl")  # type: ignore[arg-type]  # as above


def test_season_row_rejects_an_unknown_season_type() -> None:
    with pytest.raises(ValueError, match="season_type"):
        PlayerSeasonStatRow(
            player_id=1,
            season=2008,
            season_type="REG",  # type: ignore[arg-type]  # the runtime check is what's under test
            team_id=None,
            games=16,
            source="nflverse",
            sport="nfl",
            stats=PlayerStats(),
        )


def test_player_stats_default_to_not_tracked() -> None:
    assert all(getattr(PlayerStats(), f.name) is None for f in dataclasses.fields(PlayerStats))


def test_source_ids_must_be_non_empty() -> None:
    with pytest.raises(ValueError, match="source_id"):
        PlayerSourceIdRow(player_id=1, source="gsis", source_id="")
    PlayerGameStatRow(player_id=1, game_id=1, team_id=1, sport="nfl", stats=PlayerStats(attempts=1))
