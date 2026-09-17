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
    PLAYER_STAT_MAX_FIELDS,
    GameStarterRow,
    PlayerGameStatRow,
    PlayerRow,
    PlayerSeasonStatRow,
    PlayerSourceIdRow,
    PlayerStats,
)
from cfb_strength.db.connection import StaleDatabaseWarning, ensure_schema, get_conn

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


# --- issue #313: the widening to receiving, kicking and punting -------------

_PRE_313_STAT_COLUMNS = (
    "completions",
    "attempts",
    "passing_yards",
    "passing_tds",
    "passing_interceptions",
    "sacks_suffered",
    "sack_yards_lost",
    "carries",
    "rushing_yards",
    "rushing_tds",
)
"""The ten columns both stat tables held between #289 and #313, written out
rather than sliced off `PlayerStats` so that this stays a fixed historical
shape: it has to keep describing the old db after the contract moves on."""


def _build_pre_313_db(path: Path) -> None:
    """A db shaped the way #289 left it: the player tables with only the
    original ten stat columns, and a game in `games` so that
    `ensure_schema`'s staleness warning has something to fire on."""
    c = sqlite3.connect(path)
    stat_ddl = ",\n".join(f"{name} INTEGER" for name in _PRE_313_STAT_COLUMNS)
    c.executescript(
        f"""
        CREATE TABLE teams (id INTEGER PRIMARY KEY, school TEXT NOT NULL, sport TEXT);
        CREATE TABLE games (
            id INTEGER PRIMARY KEY, season INTEGER, season_type TEXT,
            home_team_id INTEGER, away_team_id INTEGER, raw_json TEXT, sport TEXT
        );
        CREATE TABLE players (
            id INTEGER PRIMARY KEY, sport TEXT NOT NULL, display_name TEXT NOT NULL,
            position TEXT, birth_date TEXT
        );
        CREATE TABLE player_game_stats (
            player_id INTEGER NOT NULL, game_id INTEGER NOT NULL,
            team_id INTEGER NOT NULL, sport TEXT NOT NULL,
            {stat_ddl},
            PRIMARY KEY (player_id, game_id)
        );
        CREATE TABLE player_season_stats (
            player_id INTEGER NOT NULL, season INTEGER NOT NULL,
            season_type TEXT NOT NULL, team_id INTEGER, games INTEGER,
            source TEXT NOT NULL, sport TEXT NOT NULL,
            {stat_ddl},
            PRIMARY KEY (player_id, season, season_type)
        );
        INSERT INTO teams (id, school, sport) VALUES (1, 'Home', 'nfl'), (2, 'Away', 'nfl');
        INSERT INTO games (id, season, season_type, home_team_id, away_team_id, raw_json, sport)
        VALUES (10, 2008, 'regular', 1, 2, '{{}}', 'nfl');
        INSERT INTO players (id, sport, display_name) VALUES (100, 'nfl', 'A Passer');
        INSERT INTO player_game_stats (player_id, game_id, team_id, sport, attempts, passing_yards)
        VALUES (100, 10, 1, 'nfl', 30, 250);
        """
    )
    c.commit()
    c.close()


def test_a_pre_313_db_gains_the_new_stat_columns(tmp_path: Path) -> None:
    db = tmp_path / "pre313.sqlite3"
    _build_pre_313_db(db)
    c = get_conn(db)
    try:
        with pytest.warns(StaleDatabaseWarning):
            ensure_schema(c)
        stat_fields = [f.name for f in dataclasses.fields(PlayerStats)]
        for table in ("player_game_stats", "player_season_stats"):
            assert _columns(c, table)[-len(stat_fields) :] == stat_fields, table
    finally:
        c.close()


def test_migrating_a_pre_313_db_preserves_the_rows_it_already_had(tmp_path: Path) -> None:
    """The widening is ALTER TABLE ADD COLUMN, not a rebuild: a stat line
    already in the db keeps its values, and the columns it has never been
    told about read NULL rather than 0 (an untracked stat is not a zero)."""
    db = tmp_path / "pre313.sqlite3"
    _build_pre_313_db(db)
    c = get_conn(db)
    try:
        with pytest.warns(StaleDatabaseWarning):
            ensure_schema(c)
        row = c.execute(
            "SELECT attempts, passing_yards, receptions, fg_made FROM player_game_stats"
        ).fetchone()
        assert (row["attempts"], row["passing_yards"]) == (30, 250)
        assert row["receptions"] is None
        assert row["fg_made"] is None
    finally:
        c.close()


def test_migrating_a_pre_313_db_matches_a_fresh_one_column_for_column(tmp_path: Path) -> None:
    """ALTER TABLE can only append, so `PlayerStats` is append-only. If a
    field were ever inserted mid-list, a fresh db and a migrated one would
    disagree here -- and only one of them would match the contract."""
    fresh = get_conn(tmp_path / "fresh.sqlite3")
    ensure_schema(fresh)
    migrated_path = tmp_path / "pre313.sqlite3"
    _build_pre_313_db(migrated_path)
    migrated = get_conn(migrated_path)
    try:
        with pytest.warns(StaleDatabaseWarning):
            ensure_schema(migrated)
        for table in ("player_game_stats", "player_season_stats"):
            assert _columns(migrated, table) == _columns(fresh, table), table
    finally:
        fresh.close()
        migrated.close()


def test_migrating_twice_is_a_no_op(tmp_path: Path) -> None:
    db = tmp_path / "pre313.sqlite3"
    _build_pre_313_db(db)
    c = get_conn(db)
    try:
        with pytest.warns(StaleDatabaseWarning):
            ensure_schema(c)
        before = _columns(c, "player_game_stats")
        ensure_schema(c)
        assert _columns(c, "player_game_stats") == before
    finally:
        c.close()


def test_max_fields_are_real_stat_columns(conn: sqlite3.Connection) -> None:
    """`PLAYER_STAT_MAX_FIELDS` names columns whose season total is a MAX,
    not a sum. A typo here would silently fall back to summing."""
    stat_fields = {f.name for f in dataclasses.fields(PlayerStats)}
    assert PLAYER_STAT_MAX_FIELDS <= stat_fields
    assert PLAYER_STAT_MAX_FIELDS == {"fg_long", "pt_long"}


def test_no_rate_or_fractional_columns_are_stored(conn: sqlite3.Connection) -> None:
    """Every stat column is a whole number in the source, which is what lets
    the DDL be uniformly INTEGER and the ingest parse with `int()`. Rate
    columns are derived from the counts beside them, and nflverse's
    `def_sacks` is fractional -- both are deliberately absent (#313, #317)."""
    stat_fields = {f.name for f in dataclasses.fields(PlayerStats)}
    assert not {f for f in stat_fields if f.endswith("_pct")}
    assert "def_sacks" not in stat_fields
    for table in ("player_game_stats", "player_season_stats"):
        types = {row["name"]: row["type"] for row in conn.execute(f"PRAGMA table_info({table})")}
        assert {types[f] for f in stat_fields} == {"INTEGER"}, table
