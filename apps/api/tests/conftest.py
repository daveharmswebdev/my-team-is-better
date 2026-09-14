"""Shared pytest fixtures for apps/api's HTTP-layer tests.

Every fixture here only ever opens the pre-baked, committed
`tests/fixtures/cfb_verdict_fixture.sqlite3` via `get_conn` -- it never
imports `cfb_strength.ratings` or `cfb_strength.ingest`. That db already has
real keener and elo ratings computed for the seven golden seasons (2001,
2003, 2004, 2005, 2013, 2017, 2019) and real CFBD mascots/aliases (see
`tests/fixtures/build_fixture.py`, a one-off generator script that is the
only place in `apps/api` allowed to import `cfb_strength.ratings` or
`cfb_strength.ingest`, and is not itself part of this pytest suite).

That "never imports ratings/ingest" is a convention here, not a checked
rule: `apps/api/.importlinter` (issue #54) has `source_modules = api`, so it
covers the installed `api` package -- i.e. `src/api/` -- and `tests/` is
outside its graph entirely. The checked boundary is the running app; keeping
the suite to the same discipline is on whoever writes the test.

`client` also wires safe, CI-friendly defaults for issue #4's persona-layer
dependencies (`get_narration_cache` -> an `InMemoryNarrationCache`,
`get_narrator` -> a stub that always returns a short, fact-block-agnostic
line) so that `test_verdict.py` -- which asserts on issue #3's evidence
blob, not on narration content -- never needs to know persona internals
exist, and never opens a real Postgres connection or calls the real Claude
API. Tests that care about narration behavior specifically (
`test_verdict_persona.py`) override these two further, on top of this
fixture, with their own scripted fakes.

`sport_client` (issue #59) is a second, function-scoped `TestClient` wired to
a freshly built, throwaway db (`tests/fixtures/sport_fixture.py`) that has
both CFB and NFL rows, plus a cross-sport name collision -- unlike
`cfb_verdict_fixture.sqlite3`, which is a CFB-only slice and has no
`sport='nfl'` rows at all. Tests that need to prove `sport` threads correctly
through the HTTP layer (`test_verdict_sport.py`, `test_catalog_sport.py`) use
this fixture instead of `client`.

`team_catalog_client` (issue #78) is a third such client, wired to
`tests/fixtures/team_catalog_fixture.py` -- two seasons either side of three
real NFL relocations, plus populated `teams.mascot`/`teams.alternate_names`
values. See that module's docstring for why neither of the other two
fixtures can cover `/api/teams`' `?year=` scoping or its mascot/alias
payload.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from cfb_strength.db.connection import get_conn
from fastapi.testclient import TestClient
from fixtures.sport_fixture import make_sport_fixture_db

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


@pytest.fixture
def sport_client(tmp_path: Path) -> Iterator[TestClient]:
    """Same wiring as `client`, but against a freshly built db
    (`tests/fixtures/sport_fixture.py`) that has both CFB and NFL rows --
    see this module's docstring."""
    from api.deps import get_db_conn, get_narration_cache, get_narrator
    from api.main import app
    from api.persona.cache import InMemoryNarrationCache

    sport_db = make_sport_fixture_db(tmp_path)

    def _override() -> Iterator[sqlite3.Connection]:
        conn = get_conn(sport_db, read_only=True)
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


@pytest.fixture
def team_catalog_client(tmp_path: Path) -> Iterator[TestClient]:
    """Same wiring as `client`, but against a freshly built db
    (`tests/fixtures/team_catalog_fixture.py`) that has NFL relocations
    across two seasons and populated mascot/alias columns -- see this
    module's docstring."""
    from fixtures.team_catalog_fixture import make_team_catalog_fixture_db

    from api.deps import get_db_conn, get_narration_cache, get_narrator
    from api.main import app
    from api.persona.cache import InMemoryNarrationCache

    catalog_db = make_team_catalog_fixture_db(tmp_path)

    def _override() -> Iterator[sqlite3.Connection]:
        conn = get_conn(catalog_db, read_only=True)
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
