"""Coverage for connection.py's in-place migration branches --
`_migrate_sport_columns` (#51, sprint 2: NFL support) and
`_migrate_team_alias_columns` (epic #76).

#51: a pre-existing local `data/cfb.sqlite3` predates the `sport`/
`source_id` columns added to teams/team_season/games/ratings/rating_breakdowns
and the widened `ingestion_log` primary key. `ensure_schema` must bring such a
db up to date in place, without losing existing rows -- CI and a fresh Render
deploy always start from an empty db (covered by the existing `empty_schema_db`
fixture elsewhere), so this file is the only place the in-place migration path
itself gets exercised.
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

import pytest

from cfb_strength.db.connection import SCHEMA_PATH, ensure_schema, get_conn

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


# ---------------------------------------------------------------------------
# Epic #76 / issue #77: teams.mascot + teams.alternate_names. Same in-place
# migration concern as the #51 block above -- and the same reason it can't
# live in schema.sql alone: `CREATE TABLE IF NOT EXISTS teams` is a no-op
# against the pre-existing db these tests build, so a column declared only
# in the DDL would silently never appear. The fixtures below deliberately
# cover *both* pre-existing shapes that exist in the wild: a pre-#51 db
# (nothing added yet) and a post-#51/pre-#77 db (sport/source_id present,
# alias columns not) -- the latter is what a real local `data/cfb.sqlite3`
# actually looks like today.
# ---------------------------------------------------------------------------

_POST_51_PRE_77_SCHEMA = """
CREATE TABLE teams (
    id INTEGER PRIMARY KEY,
    school TEXT NOT NULL,
    classification TEXT,
    sport TEXT NOT NULL DEFAULT 'cfb',
    source_id TEXT
);
"""


@pytest.fixture
def post_51_pre_77_db(tmp_path: Path) -> Path:
    """A `teams` table at the post-#51, pre-#77 shape, seeded with one CFB
    and one NFL row -- what a real local db looks like immediately before
    this migration."""
    dest = tmp_path / "post_51_pre_77.sqlite3"
    conn = sqlite3.connect(dest)
    conn.executescript(_POST_51_PRE_77_SCHEMA)
    conn.execute(
        "INSERT INTO teams (id, school, classification, sport, source_id) "
        "VALUES (251, 'Texas', 'fbs', 'cfb', NULL)"
    )
    conn.execute(
        "INSERT INTO teams (id, school, classification, sport, source_id) "
        "VALUES (1_000_000_001, 'New England Patriots', NULL, 'nfl', 'NE')"
    )
    conn.commit()
    conn.close()
    return dest


def test_migration_adds_alias_columns_to_a_pre_existing_db(post_51_pre_77_db: Path) -> None:
    conn = get_conn(post_51_pre_77_db)
    ensure_schema(conn)

    cols = {row["name"] for row in conn.execute("PRAGMA table_info(teams)")}
    assert "mascot" in cols
    assert "alternate_names" in cols

    conn.close()


def test_migration_leaves_existing_team_rows_with_null_aliases(post_51_pre_77_db: Path) -> None:
    """Backfill is the ingest's job (#77), not the migration's -- existing
    rows must survive with NULL aliases rather than being rewritten."""
    conn = get_conn(post_51_pre_77_db)
    ensure_schema(conn)

    row = conn.execute(
        "SELECT school, mascot, alternate_names FROM teams WHERE id = 251"
    ).fetchone()
    assert row["school"] == "Texas"
    assert row["mascot"] is None
    assert row["alternate_names"] is None

    assert conn.execute("SELECT COUNT(*) AS c FROM teams").fetchone()["c"] == 2

    conn.close()


def test_migration_adds_alias_columns_to_a_pre_51_db_too(pre_51_db: Path) -> None:
    """The oldest shape must land on the current schema in one pass, not
    only the one-version-behind shape above."""
    conn = get_conn(pre_51_db)
    ensure_schema(conn)

    cols = {row["name"] for row in conn.execute("PRAGMA table_info(teams)")}
    assert {"sport", "source_id", "mascot", "alternate_names"} <= cols

    conn.close()


def test_alias_migration_is_idempotent_when_run_twice(post_51_pre_77_db: Path) -> None:
    conn = get_conn(post_51_pre_77_db)
    ensure_schema(conn)
    ensure_schema(conn)  # must not raise "duplicate column name: mascot"

    assert conn.execute("SELECT COUNT(*) AS c FROM teams").fetchone()["c"] == 2
    conn.close()


def test_fresh_db_has_alias_columns_from_the_ddl(tmp_path: Path) -> None:
    """The fresh-db path must get these from schema.sql itself, so CI and a
    clean Render deploy don't depend on the migration branch at all."""
    dest = tmp_path / "fresh_alias.sqlite3"
    conn = get_conn(dest)
    conn.executescript(SCHEMA_PATH.read_text())  # DDL only -- no migration

    cols = {row["name"] for row in conn.execute("PRAGMA table_info(teams)")}
    assert "mascot" in cols
    assert "alternate_names" in cols

    conn.close()


# ---------------------------------------------------------------------------
# `check_same_thread` (issue #44). sqlite3 refuses to let a Connection be used
# from a thread other than the one that created it. That is the right default
# for the CLI, which is single-threaded and wants to hear about a mistake
# loudly. It is wrong for `apps/api`: FastAPI dispatches a sync generator
# dependency and the sync route handler to `run_in_threadpool`
# *independently*, so the thread that opens the connection in
# `api.deps.get_db_conn` is routinely not the thread the route body uses it
# on. Each connection still belongs to exactly one logical request -- it is
# never used concurrently -- so opting out of the check is safe there and
# not merely expedient.
# ---------------------------------------------------------------------------


def test_get_conn_defaults_to_rejecting_cross_thread_use(tmp_path: Path) -> None:
    """The default must stay strict, so the CLI keeps failing loudly."""
    dest = tmp_path / "same_thread.sqlite3"
    conn = get_conn(dest)
    ensure_schema(conn)

    errors: list[Exception] = []

    def use_it() -> None:
        try:
            conn.execute("SELECT 1").fetchone()
        except Exception as exc:  # noqa: BLE001 -- recording it is the assertion
            errors.append(exc)

    thread = threading.Thread(target=use_it)
    thread.start()
    thread.join()

    assert len(errors) == 1
    assert isinstance(errors[0], sqlite3.ProgrammingError)
    conn.close()


def test_get_conn_with_check_same_thread_false_allows_cross_thread_use(
    tmp_path: Path,
) -> None:
    dest = tmp_path / "cross_thread.sqlite3"
    conn = get_conn(dest, check_same_thread=False)
    ensure_schema(conn)

    results: list[int] = []
    errors: list[Exception] = []

    def use_it() -> None:
        try:
            row = conn.execute("SELECT 1 AS one").fetchone()
            results.append(int(row["one"]))
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    thread = threading.Thread(target=use_it)
    thread.start()
    thread.join()

    assert errors == []
    assert results == [1]
    conn.close()


def test_read_only_conn_also_honors_check_same_thread(tmp_path: Path) -> None:
    """The read-only branch takes a different `sqlite3.connect` call, so it
    needs its own coverage -- read_only=True is exactly what apps/api uses."""
    dest = tmp_path / "ro_cross_thread.sqlite3"
    seed = get_conn(dest)
    ensure_schema(seed)
    seed.close()

    conn = get_conn(dest, read_only=True, check_same_thread=False)
    results: list[int] = []
    errors: list[Exception] = []

    def use_it() -> None:
        try:
            row = conn.execute("SELECT COUNT(*) AS c FROM teams").fetchone()
            results.append(int(row["c"]))
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    thread = threading.Thread(target=use_it)
    thread.start()
    thread.join()

    assert errors == []
    assert results == [0]
    conn.close()
