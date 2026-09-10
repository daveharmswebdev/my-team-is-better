"""Shared pytest fixtures for apps/api's HTTP-layer tests.

Every fixture here only ever opens the pre-baked, committed
`tests/fixtures/cfb_verdict_fixture.sqlite3` via `get_conn` -- it never
imports `cfb_strength.ratings` or `cfb_strength.ingest`. That db already has
real keener ratings computed for 2001/2005/2013 (see
`tests/fixtures/build_fixture.py`, a one-off generator script that is the
only place in `apps/api` allowed to import `cfb_strength.ratings`, and is
not itself part of this pytest suite).

`client` also wires safe, CI-friendly defaults for issue #4's persona-layer
dependencies (`get_narration_cache` -> an `InMemoryNarrationCache`,
`get_narrator` -> a stub that always returns a short, fact-block-agnostic
line) so that `test_verdict.py` -- which asserts on issue #3's evidence
blob, not on narration content -- never needs to know persona internals
exist, and never opens a real Postgres connection or calls the real Claude
API. Tests that care about narration behavior specifically (
`test_verdict_persona.py`) override these two further, on top of this
fixture, with their own scripted fakes.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from cfb_strength.db.connection import get_conn
from fastapi.testclient import TestClient

FIXTURE_DB = Path(__file__).parent / "fixtures" / "cfb_verdict_fixture.sqlite3"


class _StubNarrator:
    """Default `Narrator` test double for the base `client` fixture. Its
    response has no numbers and no proper-noun team names, so it always
    passes the grounding check regardless of the fact block it's given,
    and never needs a retry -- `test_verdict.py` only cares that a
    `narration` key exists in the envelope, not what it says.
    """

    def complete(self, *, system: str, messages: list[dict[str, str]]) -> str:
        return "Solid case, no notes."


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
    from api.deps import get_db_conn, get_narration_cache, get_narrator
    from api.main import app
    from api.persona.cache import InMemoryNarrationCache

    def _override() -> Iterator[sqlite3.Connection]:
        conn = get_conn(FIXTURE_DB, read_only=True)
        try:
            yield conn
        finally:
            conn.close()

    app.dependency_overrides[get_db_conn] = _override
    app.dependency_overrides[get_narration_cache] = lambda: InMemoryNarrationCache()
    app.dependency_overrides[get_narrator] = lambda: _StubNarrator()
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db_conn, None)
        app.dependency_overrides.pop(get_narration_cache, None)
        app.dependency_overrides.pop(get_narrator, None)
