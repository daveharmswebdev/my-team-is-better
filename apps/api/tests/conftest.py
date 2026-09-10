"""Shared pytest fixtures for apps/api's HTTP-layer tests.

Every fixture here only ever opens the pre-baked, committed
`tests/fixtures/cfb_verdict_fixture.sqlite3` via `get_conn` -- it never
imports `cfb_strength.ratings` or `cfb_strength.ingest`. That db already has
real keener ratings computed for 2001/2005/2013 (see
`tests/fixtures/build_fixture.py`, a one-off generator script that is the
only place in `apps/api` allowed to import `cfb_strength.ratings`, and is
not itself part of this pytest suite).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from cfb_strength.db.connection import get_conn
from fastapi.testclient import TestClient

FIXTURE_DB = Path(__file__).parent / "fixtures" / "cfb_verdict_fixture.sqlite3"


@pytest.fixture
def client() -> Iterator[TestClient]:
    """A TestClient wired to the verdict fixture db via FastAPI dependency
    override -- no env var / module-reload trickery needed (that pattern is
    reserved for `test_config_smoke.py`, which is specifically testing
    `cfb_strength.config`'s cwd-independence, not something every test here
    should repeat).

    Mirrors production `get_db_conn`'s own lifecycle (a fresh connection
    opened and closed per request) rather than sharing one connection object
    across requests -- FastAPI's `TestClient` dispatches sync routes onto a
    worker thread, and a `sqlite3.Connection` can only be used on the thread
    that created it.
    """
    from api.deps import get_db_conn
    from api.main import app

    def _override() -> Iterator[sqlite3.Connection]:
        conn = get_conn(FIXTURE_DB, read_only=True)
        try:
            yield conn
        finally:
            conn.close()

    app.dependency_overrides[get_db_conn] = _override
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db_conn, None)
