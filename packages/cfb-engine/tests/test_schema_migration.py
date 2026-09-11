"""Coverage for connection.py's `_migrate_sport_columns` (#51, sprint 2: NFL
support): a pre-existing local `data/cfb.sqlite3` predates the `sport`/
`source_id` columns added to teams/team_season/games/ratings/rating_breakdowns
and the widened `ingestion_log` primary key. `ensure_schema` must bring such a
db up to date in place, without losing existing rows -- CI and a fresh Render
deploy always start from an empty db (covered by the existing `empty_schema_db`
fixture elsewhere), so this file is the only place the in-place migration path
itself gets exercised.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from cfb_strength.db.connection import ensure_schema, get_conn

_PRE_51_SCHEMA = """
CREATE TABLE teams (
    id INTEGER PRIMARY KEY,
    school TEXT NOT NULL,
    classification TEXT
);
CREATE TABLE team_season (
    team_id INTEGER NOT NULL REFERENCES teams(id),
    year INTEGER NOT NULL,
    conference TEXT,
    classification TEXT,
    PRIMARY KEY (team_id, year)
);
CREATE TABLE games (
    id INTEGER PRIMARY KEY,
    season INTEGER NOT NULL,
    week INTEGER,
    season_type TEXT NOT NULL,
    start_date TEXT,
    neutral_site INTEGER NOT NULL DEFAULT 0,
    completed INTEGER NOT NULL DEFAULT 0,
    home_team_id INTEGER NOT NULL REFERENCES teams(id),
    away_team_id INTEGER NOT NULL REFERENCES teams(id),
    home_team TEXT NOT NULL,
    away_team TEXT NOT NULL,
    home_points INTEGER,
    away_points INTEGER,
    home_conference TEXT,
    away_conference TEXT,
    venue TEXT,
    raw_json TEXT NOT NULL
);
CREATE TABLE ratings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    year INTEGER NOT NULL,
    method TEXT NOT NULL DEFAULT 'keener',
    team_id INTEGER NOT NULL REFERENCES teams(id),
    rating REAL NOT NULL,
    rank INTEGER NOT NULL,
    wins INTEGER NOT NULL,
    losses INTEGER NOT NULL,
    computed_at TEXT NOT NULL,
    UNIQUE(year, method, team_id)
);
CREATE TABLE rating_breakdowns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    year INTEGER NOT NULL,
    method TEXT NOT NULL DEFAULT 'keener',
    team_id INTEGER NOT NULL REFERENCES teams(id),
    opponent_team_id INTEGER REFERENCES teams(id),
    games_played INTEGER,
    wins INTEGER,
    losses INTEGER,
    credit REAL,
    contribution REAL NOT NULL,
    computed_at TEXT NOT NULL
);
CREATE TABLE ingestion_log (
    year INTEGER NOT NULL,
    season_type TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    game_count INTEGER NOT NULL,
    status TEXT NOT NULL,
    PRIMARY KEY (year, season_type)
);
"""


@pytest.fixture
def pre_51_db(tmp_path: Path) -> Path:
    """A db built from the exact pre-#51 schema, seeded with one CFB team,
    one game, one rating, one rating_breakdown row, and one ingestion_log
    row -- so the migration test can assert every one of them survives."""
    dest = tmp_path / "pre_51.sqlite3"
    conn = sqlite3.connect(dest)
    conn.executescript(_PRE_51_SCHEMA)
    conn.execute("INSERT INTO teams (id, school, classification) VALUES (333, 'Alabama', 'fbs')")
    conn.execute(
        "INSERT INTO team_season (team_id, year, conference, classification) "
        "VALUES (333, 2005, 'SEC', 'fbs')"
    )
    conn.execute(
        """
        INSERT INTO games (
            id, season, week, season_type, start_date, neutral_site, completed,
            home_team_id, away_team_id, home_team, away_team, home_points,
            away_points, home_conference, away_conference, venue, raw_json
        ) VALUES (
            1, 2005, 1, 'regular', '2005-09-01', 0, 1,
            333, 333, 'Alabama', 'Alabama', 24, 10, 'SEC', 'SEC', 'Bryant-Denny', '{}'
        )
        """
    )
    conn.execute(
        "INSERT INTO ratings (year, method, team_id, rating, rank, wins, losses, computed_at) "
        "VALUES (2005, 'keener', 333, 1.5, 1, 12, 1, '2026-01-01T00:00:00+00:00')"
    )
    conn.execute(
        "INSERT INTO rating_breakdowns "
        "(year, method, team_id, opponent_team_id, games_played, wins, losses, credit, "
        "contribution, computed_at) "
        "VALUES (2005, 'keener', 333, NULL, NULL, NULL, NULL, NULL, 0.1, '2026-01-01T00:00:00+00:00')"
    )
    conn.execute(
        "INSERT INTO ingestion_log (year, season_type, fetched_at, game_count, status) "
        "VALUES (2005, 'regular', '2026-01-01T00:00:00+00:00', 890, 'ok')"
    )
    conn.commit()
    conn.close()
    return dest


def test_migration_adds_sport_column_defaulting_existing_rows_to_cfb(pre_51_db: Path) -> None:
    conn = get_conn(pre_51_db)
    ensure_schema(conn)

    for table in ("teams", "team_season", "games", "ratings", "rating_breakdowns"):
        row = conn.execute(f"SELECT sport FROM {table} LIMIT 1").fetchone()
        assert row["sport"] == "cfb", f"{table} row was not backfilled to sport='cfb'"

    conn.close()


def test_migration_adds_source_id_column_nullable_for_existing_rows(pre_51_db: Path) -> None:
    conn = get_conn(pre_51_db)
    ensure_schema(conn)

    team = conn.execute("SELECT source_id FROM teams WHERE id = 333").fetchone()
    game = conn.execute("SELECT source_id FROM games WHERE id = 1").fetchone()
    assert team["source_id"] is None
    assert game["source_id"] is None

    conn.close()


def test_migration_preserves_existing_rows_and_ids(pre_51_db: Path) -> None:
    conn = get_conn(pre_51_db)
    ensure_schema(conn)

    assert conn.execute("SELECT COUNT(*) AS c FROM teams").fetchone()["c"] == 1
    assert conn.execute("SELECT COUNT(*) AS c FROM games").fetchone()["c"] == 1
    assert conn.execute("SELECT COUNT(*) AS c FROM ratings").fetchone()["c"] == 1
    assert conn.execute("SELECT COUNT(*) AS c FROM rating_breakdowns").fetchone()["c"] == 1

    game = conn.execute("SELECT home_team, away_points FROM games WHERE id = 1").fetchone()
    assert game["home_team"] == "Alabama"
    assert game["away_points"] == 10

    conn.close()


def test_migration_widens_ingestion_log_primary_key_to_include_sport(pre_51_db: Path) -> None:
    """ingestion_log is dropped and recreated (not migrated in place -- see
    connection.py's comment: it's a regenerable operational log, not data
    worth preserving across this specific migration, unlike every other
    table this fixture seeds). Confirm the widened PK actually takes effect:
    a CFB and an NFL row for the same year/season_type must both be storable
    without one clobbering the other."""
    conn = get_conn(pre_51_db)
    ensure_schema(conn)

    assert conn.execute("SELECT COUNT(*) AS c FROM ingestion_log").fetchone()["c"] == 0

    conn.execute(
        "INSERT INTO ingestion_log (year, season_type, fetched_at, game_count, status, sport) "
        "VALUES (2005, 'regular', '2026-01-01T00:00:00+00:00', 890, 'ok', 'cfb')"
    )
    conn.execute(
        "INSERT INTO ingestion_log (year, season_type, fetched_at, game_count, status, sport) "
        "VALUES (2005, 'regular', '2026-01-01T00:00:00+00:00', 285, 'ok', 'nfl')"
    )
    conn.commit()

    rows = conn.execute(
        "SELECT sport, game_count FROM ingestion_log WHERE year = 2005 AND season_type = 'regular' "
        "ORDER BY sport"
    ).fetchall()
    assert [(r["sport"], r["game_count"]) for r in rows] == [("cfb", 890), ("nfl", 285)]

    conn.close()


def test_migration_creates_unique_indexes_on_source_id(pre_51_db: Path) -> None:
    conn = get_conn(pre_51_db)
    ensure_schema(conn)

    conn.execute(
        "INSERT INTO teams (id, school, classification, sport, source_id) "
        "VALUES (1_000_000_001, 'Kansas City Chiefs', NULL, 'nfl', 'KC')"
    )
    conn.commit()

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO teams (id, school, classification, sport, source_id) "
            "VALUES (1_000_000_002, 'Duplicate', NULL, 'nfl', 'KC')"
        )

    conn.close()


def test_migration_is_idempotent_when_run_twice(pre_51_db: Path) -> None:
    conn = get_conn(pre_51_db)
    ensure_schema(conn)
    ensure_schema(conn)  # must not raise (e.g. "duplicate column name")

    assert conn.execute("SELECT COUNT(*) AS c FROM teams").fetchone()["c"] == 1
    conn.close()


def test_ensure_schema_on_fresh_db_has_new_columns_from_the_start(tmp_path: Path) -> None:
    dest = tmp_path / "fresh.sqlite3"
    conn = get_conn(dest)
    ensure_schema(conn)

    for table in ("teams", "team_season", "games", "ratings", "rating_breakdowns", "ingestion_log"):
        cols = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        assert "sport" in cols

    conn.close()
