"""Issue #385: a stale database fails as `StaleDatabaseError`, whichever
late-added column or table it lacks.

apps/api and the MCP server open the db read-only and never run
`ensure_schema`, so a db built before a column existed still lacks it when
evidence queries it. Without a guard that is a bare
`sqlite3.OperationalError: no such column` (a 500). With it, it is
`StaleDatabaseError` naming what is missing, which the API maps to 503
`stale_database` (#280).

"Late-added" means added to `db/schema.sql` after the scaffold commit
(`git log -S <column> -- db/schema.sql`), so a db built before it exists in
the wild. `neutral_site` is in the scaffold schema, so it is not one. Only
the late-added names the evidence layer actually reads are listed:
`teams.source_id`, `games.source_id`, `teams.mascot` and the
`team_season.sport` column are late-added too, but evidence never reads them.

The list below is written out by hand on purpose, not imported from
`proof.py`: it is the independent statement of what the guard must cover, so
dropping a name from the guard's own list turns exactly that case red.

Each case drops one column (or table) from a copy of the committed CFB
regression fixture, rated for 2005 under `elo` (so the ledger tables hold
rows), and never touches the committed file.
"""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest

from cfb_strength.db.connection import get_conn
from cfb_strength.evidence.proof import (
    StaleDatabaseError,
    build_comparison,
    build_team_case,
)
from cfb_strength.ratings.compute_ratings import compute_and_store
from tests.conftest import REGRESSION_FIXTURE_DB

YEAR = 2005
METHOD = "elo"

# (table, column, issue that added it) for every late-added column evidence reads.
LATE_ADDED_COLUMNS: tuple[tuple[str, str], ...] = (
    ("teams", "sport"),  # #51
    ("teams", "alternate_names"),  # #76
    ("games", "sport"),  # #51
    ("games", "conference_championship"),  # #300
    ("ratings", "sport"),  # #51
    ("ratings", "ties"),  # #83
    ("rating_breakdowns", "sport"),  # #51
    ("elo_ledger_configs", "mov_denom_floor_fraction"),  # #194
)

# Every late-added table evidence reads.
LATE_ADDED_TABLES: tuple[str, ...] = (
    "rating_breakdowns",  # #31
    "elo_ledger_configs",  # #183
    "elo_ledger_steps",  # #183
)


@pytest.fixture(scope="module")
def rated_db(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A copy of the CFB fixture with 2005 rated under elo: every evidence
    table holds rows for the teams the cases ask about."""
    dest = tmp_path_factory.mktemp("stale_columns") / "rated.sqlite3"
    shutil.copy(REGRESSION_FIXTURE_DB, dest)
    conn = get_conn(dest)
    try:
        compute_and_store(conn, YEAR, METHOD)
        conn.commit()
    finally:
        conn.close()
    return dest


def _copy(rated_db: Path, tmp_path: Path) -> Path:
    dest = tmp_path / "stale.sqlite3"
    shutil.copy(rated_db, dest)
    return dest


def _drop_column(db_path: Path, table: str, column: str) -> None:
    """Rebuild `table` without `column`, SQLite's documented recipe (its
    DROP COLUMN can't re-parse schema.sql's commented DDL for every column)."""
    conn = get_conn(db_path)
    try:
        kept = [row["name"] for row in conn.execute(f"PRAGMA table_info({table})")]
        assert column in kept, f"{table}.{column} is not in the fixture's schema"
        kept.remove(column)
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute(f"CREATE TABLE {table}_stale AS SELECT {', '.join(kept)} FROM {table}")
        conn.execute(f"DROP TABLE {table}")
        conn.execute(f"ALTER TABLE {table}_stale RENAME TO {table}")
        conn.commit()
    finally:
        conn.close()


def _drop_table(db_path: Path, table: str) -> None:
    conn = get_conn(db_path)
    try:
        conn.execute(f"DROP TABLE {table}")
        conn.commit()
    finally:
        conn.close()


def _raises_stale(conn: sqlite3.Connection) -> list[StaleDatabaseError]:
    """The error each public evidence entry point raises on `conn`."""
    errors: list[StaleDatabaseError] = []
    with pytest.raises(StaleDatabaseError) as case_info:
        build_team_case(conn, YEAR, "Texas", method=METHOD, sport="cfb")
    errors.append(case_info.value)
    with pytest.raises(StaleDatabaseError) as comparison_info:
        build_comparison(conn, YEAR, "Texas", "USC", method=METHOD, sport="cfb")
    errors.append(comparison_info.value)
    return errors


def test_the_unmodified_copy_is_not_stale(rated_db: Path, tmp_path: Path) -> None:
    """Control: the cases below fail only because of what they drop."""
    conn = get_conn(_copy(rated_db, tmp_path), read_only=True)
    try:
        case = build_team_case(conn, YEAR, "Texas", method=METHOD, sport="cfb")
        build_comparison(conn, YEAR, "Texas", "USC", method=METHOD, sport="cfb")
    finally:
        conn.close()
    assert case.elo_ledger is not None


@pytest.mark.parametrize(
    ("table", "column"), LATE_ADDED_COLUMNS, ids=[f"{t}.{c}" for t, c in LATE_ADDED_COLUMNS]
)
def test_missing_late_added_column_raises_stale_database_error(
    rated_db: Path, tmp_path: Path, table: str, column: str
) -> None:
    db_path = _copy(rated_db, tmp_path)
    _drop_column(db_path, table, column)
    conn = get_conn(db_path, read_only=True)
    try:
        errors = _raises_stale(conn)
    finally:
        conn.close()

    for error in errors:
        assert not isinstance(error, sqlite3.OperationalError)
        assert error.missing_columns == (f"{table}.{column}",)
        assert error.missing_tables == ()
        assert f"{table}.{column}" in str(error)
        assert "cfb doctor" in str(error)


@pytest.mark.parametrize("table", LATE_ADDED_TABLES)
def test_missing_late_added_table_raises_stale_database_error(
    rated_db: Path, tmp_path: Path, table: str
) -> None:
    """A missing table is named as a table; its own late-added columns are
    not reported as missing on top of it."""
    db_path = _copy(rated_db, tmp_path)
    _drop_table(db_path, table)
    conn = get_conn(db_path, read_only=True)
    try:
        errors = _raises_stale(conn)
    finally:
        conn.close()

    for error in errors:
        assert error.missing_tables == (table,)
        assert error.missing_columns == ()
        assert table in str(error)
        assert "cfb doctor" in str(error)


def test_every_missing_column_is_named_at_once(rated_db: Path, tmp_path: Path) -> None:
    """One check names everything absent, not just the first thing it trips
    over, so one rebuild fixes it."""
    db_path = _copy(rated_db, tmp_path)
    _drop_column(db_path, "ratings", "ties")
    _drop_column(db_path, "games", "conference_championship")
    conn = get_conn(db_path, read_only=True)
    try:
        errors = _raises_stale(conn)
    finally:
        conn.close()

    for error in errors:
        assert set(error.missing_columns) == {"ratings.ties", "games.conference_championship"}
        assert "#83" in str(error)
        assert "#300" in str(error)
