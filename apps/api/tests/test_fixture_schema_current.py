"""Issue #335: a committed fixture db that has fallen behind the engine
schema fails here, once, by name, instead of as dozens of `no such column`
errors scattered across the suite.

Every committed `*.sqlite3` under `tests/fixtures/` is globbed, so a new
committed fixture is covered without editing this file. Each is copied to
`tmp_path` first: `ensure_schema` migrates in place, and running it on the
committed file would rewrite it.

Like the rest of this suite it opens dbs only through `cfb_strength.db`
(never `cfb_strength.ingest` or `cfb_strength.ratings`; see conftest.py).
`test_players_widened_stats.py`'s narrower column check stays as it is.
"""

from __future__ import annotations

import shutil
import warnings
from pathlib import Path

import pytest
from cfb_strength.db.connection import StaleDatabaseWarning, ensure_schema, get_conn

FIXTURES_DIR = Path(__file__).parent / "fixtures"
COMMITTED_FIXTURES = sorted(FIXTURES_DIR.glob("*.sqlite3"))
REBUILD_MESSAGE = "this fixture is stale: rebuild it with tests/fixtures/build_fixture.py"


def _copy(fixture: Path, tmp_path: Path) -> Path:
    copy = tmp_path / fixture.name
    shutil.copyfile(fixture, copy)
    return copy


def assert_fixture_schema_current(db_path: Path) -> None:
    """Fail with the rebuild message if `ensure_schema` finds `db_path` stale.

    Mutates `db_path` (that's how `ensure_schema` works), so pass a copy.
    """
    conn = get_conn(db_path)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", StaleDatabaseWarning)
            try:
                ensure_schema(conn)
            except StaleDatabaseWarning as stale:
                pytest.fail(f"{db_path.name}: {REBUILD_MESSAGE}\n\n{stale}")
    finally:
        conn.close()


def test_there_is_a_committed_fixture_to_check() -> None:
    # Without this, a moved fixtures dir would make the parametrized test
    # below collect zero cases and pass vacuously.
    assert COMMITTED_FIXTURES


@pytest.mark.parametrize("fixture", COMMITTED_FIXTURES, ids=lambda p: p.name)
def test_committed_fixture_matches_the_engine_schema(fixture: Path, tmp_path: Path) -> None:
    assert_fixture_schema_current(_copy(fixture, tmp_path))


def test_a_stale_fixture_fails_with_the_rebuild_message(tmp_path: Path) -> None:
    """Pins the check itself, so it can't go vacuous: a copy missing one
    contract column must fail, naming build_fixture.py."""
    stale = _copy(FIXTURES_DIR / "cfb_verdict_fixture.sqlite3", tmp_path)
    conn = get_conn(stale)
    try:
        conn.execute("ALTER TABLE player_season_stats DROP COLUMN rushing_first_downs")
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(pytest.fail.Exception) as failure:
        assert_fixture_schema_current(stale)

    assert REBUILD_MESSAGE in str(failure.value)
    assert "player_season_stats.rushing_first_downs" in str(failure.value)
