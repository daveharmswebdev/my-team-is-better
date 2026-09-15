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
import warnings
from pathlib import Path

import pytest

from cfb_strength.db.connection import SCHEMA_PATH, StaleDatabaseWarning, ensure_schema, get_conn

# Issue #97: migrating a db that already holds games emits
# `StaleDatabaseWarning`. The tests carrying this mark migrate the populated
# `pre_51_db` fixture on purpose -- the warning is expected there, and is
# asserted by the dedicated warning tests further down, so it is ignored
# only on these tests rather than globally.
_MIGRATES_A_POPULATED_STALE_DB = pytest.mark.filterwarnings(
    "ignore::cfb_strength.db.connection.StaleDatabaseWarning"
)

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
        "VALUES (2005, 'keener', 333, NULL, NULL, NULL, NULL, NULL, 0.1, "
        "'2026-01-01T00:00:00+00:00')"
    )
    conn.execute(
        "INSERT INTO ingestion_log (year, season_type, fetched_at, game_count, status) "
        "VALUES (2005, 'regular', '2026-01-01T00:00:00+00:00', 890, 'ok')"
    )
    conn.commit()
    conn.close()
    return dest


@_MIGRATES_A_POPULATED_STALE_DB
def test_migration_adds_sport_column_defaulting_existing_rows_to_cfb(pre_51_db: Path) -> None:
    conn = get_conn(pre_51_db)
    ensure_schema(conn)

    for table in ("teams", "team_season", "games", "ratings", "rating_breakdowns"):
        row = conn.execute(f"SELECT sport FROM {table} LIMIT 1").fetchone()
        assert row["sport"] == "cfb", f"{table} row was not backfilled to sport='cfb'"

    conn.close()


@_MIGRATES_A_POPULATED_STALE_DB
def test_migration_adds_source_id_column_nullable_for_existing_rows(pre_51_db: Path) -> None:
    conn = get_conn(pre_51_db)
    ensure_schema(conn)

    team = conn.execute("SELECT source_id FROM teams WHERE id = 333").fetchone()
    game = conn.execute("SELECT source_id FROM games WHERE id = 1").fetchone()
    assert team["source_id"] is None
    assert game["source_id"] is None

    conn.close()


@_MIGRATES_A_POPULATED_STALE_DB
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


@_MIGRATES_A_POPULATED_STALE_DB
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


@_MIGRATES_A_POPULATED_STALE_DB
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


@_MIGRATES_A_POPULATED_STALE_DB
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


@_MIGRATES_A_POPULATED_STALE_DB
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
# Issue #83: ratings.ties. A real NFL tie (2016 CIN-WAS 27-27) was dropped
# from every displayed record -- the Bengals read 6-9, not 6-9-1 -- because
# `ratings` could only store wins and losses. Same in-place migration concern
# as the blocks above: `CREATE TABLE IF NOT EXISTS ratings` is a no-op
# against a pre-existing db, so the column has to be added in connection.py.
# Existing rows backfill to 0, which is honest only until the next `cfb rate`
# (production always builds from an empty db, so it never sees that window).
# ---------------------------------------------------------------------------


@_MIGRATES_A_POPULATED_STALE_DB
def test_migration_adds_ties_column_defaulting_existing_ratings_to_zero(pre_51_db: Path) -> None:
    conn = get_conn(pre_51_db)
    ensure_schema(conn)

    row = conn.execute("SELECT wins, losses, ties FROM ratings WHERE team_id = 333").fetchone()
    assert (row["wins"], row["losses"], row["ties"]) == (12, 1, 0)

    conn.close()


@_MIGRATES_A_POPULATED_STALE_DB
def test_ties_migration_is_idempotent_when_run_twice(pre_51_db: Path) -> None:
    conn = get_conn(pre_51_db)
    ensure_schema(conn)
    ensure_schema(conn)  # must not raise "duplicate column name: ties"

    assert conn.execute("SELECT COUNT(*) AS c FROM ratings").fetchone()["c"] == 1
    conn.close()


def test_fresh_db_has_ties_column_from_the_ddl(tmp_path: Path) -> None:
    """CI and a clean Render deploy must get `ties` from schema.sql itself,
    not depend on the migration branch."""
    dest = tmp_path / "fresh_ties.sqlite3"
    conn = get_conn(dest)
    conn.executescript(SCHEMA_PATH.read_text())  # DDL only -- no migration

    cols = {row["name"]: row for row in conn.execute("PRAGMA table_info(ratings)")}
    assert "ties" in cols
    assert cols["ties"]["notnull"] == 1

    conn.close()


# ---------------------------------------------------------------------------
# Issue #97: StaleDatabaseWarning. Schema currency disguises data staleness --
# `ensure_schema` migrates the missing columns into a pre-#51 db and the
# result looks current while holding no NFL rows and no mascots. A migration
# that actually fires (a `_has_column` check came back False) on a db that
# already holds games is the one moment the code *knows* the data predates
# the schema, so it says so. It must stay quiet for a fresh db, an already
# current db, and an empty pre-existing db (no data to be stale).
# ---------------------------------------------------------------------------


def _stale_warnings_from_ensure_schema(db: Path) -> list[warnings.WarningMessage]:
    conn = get_conn(db)
    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            ensure_schema(conn)
    finally:
        conn.close()
    return [w for w in caught if issubclass(w.category, StaleDatabaseWarning)]


def _insert_one_team_and_game(conn: sqlite3.Connection) -> None:
    conn.execute("INSERT INTO teams (id, school, classification) VALUES (251, 'Texas', 'fbs')")
    conn.execute(
        """
        INSERT INTO games (
            id, season, week, season_type, completed, home_team_id, away_team_id,
            home_team, away_team, home_points, away_points, raw_json
        ) VALUES (1, 2005, 1, 'regular', 1, 251, 251, 'Texas', 'Texas', 41, 38, '{}')
        """
    )


def test_stale_warning_fires_when_migrating_a_populated_pre_51_db(pre_51_db: Path) -> None:
    stale = _stale_warnings_from_ensure_schema(pre_51_db)

    assert len(stale) == 1
    message = str(stale[0].message)
    assert str(pre_51_db) in message
    assert "predates the current schema" in message
    assert "cfb doctor" in message
    # Every migration family must report what it added, not just one of them.
    for added in ("games.sport", "teams.source_id", "teams.mascot", "ratings.ties"):
        assert added in message


@pytest.mark.parametrize(
    "dropped",
    [
        pytest.param(
            (("teams", "mascot"), ("teams", "alternate_names"), ("ratings", "ties")),
            id="post_51_pre_77",
        ),
        pytest.param((("ratings", "ties"),), id="post_77_pre_83"),
    ],
)
def test_stale_warning_fires_when_migrating_a_populated_post_51_db(
    tmp_path: Path, dropped: tuple[tuple[str, str], ...]
) -> None:
    # `ALTER TABLE ... DROP COLUMN` needs SQLite >= 3.35 (2021). CI's
    # python-build-standalone interpreter bundles a far newer SQLite.
    db = tmp_path / "post_51.sqlite3"
    conn = sqlite3.connect(db)
    conn.executescript(SCHEMA_PATH.read_text())
    for table, column in dropped:
        conn.execute(f"ALTER TABLE {table} DROP COLUMN {column}")
    _insert_one_team_and_game(conn)
    conn.commit()
    conn.close()

    stale = _stale_warnings_from_ensure_schema(db)

    assert len(stale) == 1
    message = str(stale[0].message)
    assert "predates the current schema" in message
    for table, column in dropped:
        assert f"{table}.{column}" in message


@pytest.mark.parametrize(
    ("statement", "created"),
    [
        pytest.param("DROP TABLE rating_breakdowns", "rating_breakdowns", id="table"),
        pytest.param("DROP INDEX idx_games_season", "idx_games_season", id="index"),
        pytest.param("DROP INDEX idx_teams_source_id", "idx_teams_source_id", id="migration_index"),
    ],
)
def test_stale_warning_fires_when_a_populated_db_gains_a_table_or_index(
    tmp_path: Path, statement: str, created: str
) -> None:
    """Not only ALTER TABLE: a whole table or index that `CREATE ... IF NOT
    EXISTS` has to add to a db already holding games is the same signal."""
    db = tmp_path / "missing_object.sqlite3"
    conn = get_conn(db)
    ensure_schema(conn)
    _insert_one_team_and_game(conn)
    conn.execute(statement)
    conn.commit()
    conn.close()

    stale = _stale_warnings_from_ensure_schema(db)

    assert len(stale) == 1
    assert created in str(stale[0].message)


def test_stale_warning_does_not_fire_for_populated_teams_with_empty_games(tmp_path: Path) -> None:
    """The signal is games, not any table: a pre-existing db with teams but
    no games holds nothing a season-level check could call stale."""
    db = tmp_path / "teams_only_pre_51.sqlite3"
    conn = sqlite3.connect(db)
    conn.executescript(_PRE_51_SCHEMA)
    conn.execute("INSERT INTO teams (id, school, classification) VALUES (251, 'Texas', 'fbs')")
    conn.commit()
    conn.close()

    assert _stale_warnings_from_ensure_schema(db) == []


def test_stale_warning_does_not_fire_for_a_fresh_db(tmp_path: Path) -> None:
    assert _stale_warnings_from_ensure_schema(tmp_path / "fresh.sqlite3") == []


def test_stale_warning_does_not_fire_for_a_populated_current_db(tmp_path: Path) -> None:
    db = tmp_path / "current.sqlite3"
    conn = get_conn(db)
    ensure_schema(conn)
    _insert_one_team_and_game(conn)
    conn.commit()
    conn.close()

    assert _stale_warnings_from_ensure_schema(db) == []


def test_stale_warning_does_not_fire_for_an_empty_pre_existing_db(tmp_path: Path) -> None:
    db = tmp_path / "empty_pre_51.sqlite3"
    conn = sqlite3.connect(db)
    conn.executescript(_PRE_51_SCHEMA)
    conn.commit()
    conn.close()

    assert _stale_warnings_from_ensure_schema(db) == []

    # Not vacuous: the migration really did fire on this db -- it just had no
    # data that could be stale.
    check = get_conn(db, read_only=True)
    cols = {row["name"] for row in check.execute("PRAGMA table_info(teams)")}
    check.close()
    assert {"sport", "mascot", "alternate_names"} <= cols


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


# ---------------------------------------------------------------------------
# `immutable` (issue #97). `cfb doctor` must read a WAL-mode db that arrives
# without its -wal/-shm files (a copied db, or one closed cleanly on Linux)
# without creating those files. A plain read-only open is platform-dependent
# there: macOS's SQLite refuses it, Linux's may succeed by creating them.
# `immutable=1` reads the main file as-is and writes nothing; it is only
# correct when no -wal file exists, and choosing when is the caller's job.
# ---------------------------------------------------------------------------


def test_get_conn_rejects_immutable_without_read_only(tmp_path: Path) -> None:
    dest = tmp_path / "never_created.sqlite3"

    with pytest.raises(ValueError, match="read_only"):
        get_conn(dest, immutable=True)

    assert not dest.exists()


def test_immutable_read_only_conn_reads_a_wal_db_without_creating_sidecar_files(
    tmp_path: Path,
) -> None:
    dest = tmp_path / "wal.sqlite3"
    seed = get_conn(dest)
    ensure_schema(seed)
    _insert_one_team_and_game(seed)
    seed.commit()
    assert seed.execute("PRAGMA journal_mode = WAL").fetchone()[0] == "wal"
    seed.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    seed.close()
    for suffix in ("-wal", "-shm"):
        Path(f"{dest}{suffix}").unlink(missing_ok=True)

    conn = get_conn(dest, read_only=True, immutable=True)
    try:
        assert conn.execute("SELECT COUNT(*) AS c FROM games").fetchone()["c"] == 1
    finally:
        conn.close()

    assert sorted(p.name for p in tmp_path.iterdir()) == ["wal.sqlite3"]


# ---------------------------------------------------------------------------
# Issue #194: elo_ledger_configs.mov_denom_floor_fraction. A db whose ledger
# table predates the column gets it via ALTER TABLE, backfilled to 0.5 (the
# only value `_MIN_DENOM_FRACTION` has ever had, so the backfill records what
# those walks ran with). A fresh db gets it from the DDL, NOT NULL and with
# no default, so a new config row must state its fraction.
# ---------------------------------------------------------------------------

_PRE_194_LEDGER_CONFIGS_DDL = """
CREATE TABLE elo_ledger_configs (
    year INTEGER NOT NULL,
    method TEXT NOT NULL,
    sport TEXT NOT NULL,
    starting_rating REAL NOT NULL,
    k REAL NOT NULL,
    hfa REAL NOT NULL,
    scale REAL NOT NULL,
    mov_scale REAL NOT NULL,
    mov_autocorr REAL NOT NULL,
    computed_at TEXT NOT NULL,
    PRIMARY KEY (year, method, sport)
);
"""


@pytest.fixture
def pre_194_db(tmp_path: Path) -> Path:
    """An otherwise-current db whose `elo_ledger_configs` lacks
    `mov_denom_floor_fraction`, holding one 2005 cfb elo config row."""
    dest = tmp_path / "pre_194.sqlite3"
    conn = get_conn(dest)
    ddl = SCHEMA_PATH.read_text()
    start = ddl.index("CREATE TABLE IF NOT EXISTS elo_ledger_configs")
    end = ddl.index(";", start) + 1
    conn.executescript(ddl[:start] + _PRE_194_LEDGER_CONFIGS_DDL + ddl[end:])
    conn.execute(
        "INSERT INTO elo_ledger_configs (year, method, sport, starting_rating, k, hfa, "
        "scale, mov_scale, mov_autocorr, computed_at) "
        "VALUES (2005, 'elo', 'cfb', 1500.0, 40.0, 100.0, 400.0, 2.2, 0.001, 'x')"
    )
    conn.commit()
    conn.close()
    return dest


def test_migration_adds_floor_fraction_column_backfilling_existing_rows_to_half(
    pre_194_db: Path,
) -> None:
    conn = get_conn(pre_194_db)
    ensure_schema(conn)

    row = conn.execute(
        "SELECT mov_scale, mov_denom_floor_fraction FROM elo_ledger_configs "
        "WHERE year = 2005 AND method = 'elo' AND sport = 'cfb'"
    ).fetchone()
    assert (row["mov_scale"], row["mov_denom_floor_fraction"]) == (2.2, 0.5)
    conn.close()


def test_floor_fraction_migration_is_idempotent_when_run_twice(pre_194_db: Path) -> None:
    conn = get_conn(pre_194_db)
    ensure_schema(conn)
    ensure_schema(conn)  # must not raise "duplicate column name"

    assert conn.execute("SELECT COUNT(*) AS c FROM elo_ledger_configs").fetchone()["c"] == 1
    conn.close()


def test_fresh_db_has_floor_fraction_column_from_the_ddl_with_no_default(tmp_path: Path) -> None:
    """A clean Render build must get the column from schema.sql itself, and a
    new config row must state its fraction rather than inherit a default."""
    dest = tmp_path / "fresh_floor.sqlite3"
    conn = get_conn(dest)
    conn.executescript(SCHEMA_PATH.read_text())  # DDL only -- no migration

    cols = {row["name"]: row for row in conn.execute("PRAGMA table_info(elo_ledger_configs)")}
    assert "mov_denom_floor_fraction" in cols
    assert cols["mov_denom_floor_fraction"]["notnull"] == 1
    assert cols["mov_denom_floor_fraction"]["dflt_value"] is None
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO elo_ledger_configs (year, method, sport, starting_rating, k, hfa, "
            "scale, mov_scale, mov_autocorr, computed_at) "
            "VALUES (2005, 'elo', 'cfb', 1500.0, 40.0, 100.0, 400.0, 2.2, 0.001, 'x')"
        )
    conn.close()
