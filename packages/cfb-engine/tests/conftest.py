"""Shared pytest fixtures for integration/regression coverage.

Owned by test-writer. Everything here is either:
  - a writable per-test copy of the committed regression fixture db
    (tests/fixtures/cfb_regression.sqlite3), or
  - a small helper for loading the real cached raw-JSON game sample
    (tests/fixtures/raw_games_sample.json).

Neither ever touches the live `data/cfb.sqlite3` build artifact and neither
makes a live CFBD API call -- see tests/fixtures/README (build_fixture notes
in test_golden_dataset_regressions.py's module docstring) for how the
fixture db was produced.
"""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest

from cfb_strength.db.connection import get_conn

FIXTURES_DIR = Path(__file__).parent / "fixtures"
REGRESSION_FIXTURE_DB = FIXTURES_DIR / "cfb_regression.sqlite3"
RAW_GAMES_SAMPLE = FIXTURES_DIR / "raw_games_sample.json"


@pytest.fixture
def regression_db(tmp_path: Path) -> Path:
    """A writable per-test copy of the committed 2001/2005/2013 fixture db
    (teams/team_season/games only -- no precomputed `ratings` rows, so any
    test using this fixture must run the real rating computation itself
    rather than reading a canned answer)."""
    dest = tmp_path / "cfb_regression.sqlite3"
    shutil.copy(REGRESSION_FIXTURE_DB, dest)
    return dest


@pytest.fixture
def regression_conn(regression_db: Path):
    conn = get_conn(regression_db)
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture
def empty_schema_db(tmp_path: Path) -> Path:
    """A fresh sqlite db with the real schema.sql applied, no rows at all --
    for ingest-integration tests that write from scratch."""
    from cfb_strength.db.connection import ensure_schema

    dest = tmp_path / "empty.sqlite3"
    conn = get_conn(dest)
    ensure_schema(conn)
    conn.close()
    return dest
