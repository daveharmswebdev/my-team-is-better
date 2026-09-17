"""Regression tests for GitHub issue #44 -- intermittent HTTP 500s from
`sqlite3.ProgrammingError: SQLite objects created in a thread can only be
used in that same thread`.

`api.deps.get_db_conn` opens a fresh connection per request, which *looks*
thread-safe by construction (nothing shared, nothing cached). It isn't:
FastAPI/Starlette dispatches each sync callable in the dependency-resolution
chain to `run_in_threadpool` *independently*, so the sync generator
dependency's `yield` can run on a different worker thread than the sync route
handler that then uses the yielded `Connection`. Under load those are
routinely two different pool threads, and sqlite rejects the second one.

Both tests below need *real* concurrency to have any value. The rest of this
suite issues `TestClient` requests serially, so the dependency and the route
keep getting handed the same idle worker thread back and every serial request
passes whether or not the bug is present -- which is exactly why 117 green
tests never caught a bug that reproduces against a booted server in four
concurrent GETs. So:

- `test_get_db_conn_connection_is_usable_from_another_thread` is the cheap,
  deterministic guard: it asserts directly on the threading property
  `get_db_conn` must have, with no HTTP layer or scheduler luck involved.
- `test_concurrent_requests_never_return_500` is the end-to-end proof, and
  deliberately drives the *real* `get_db_conn` (only `DB_PATH` is redirected
  at the fixture db) rather than `tests/conftest.py`'s
  `app.dependency_overrides` stand-in -- an override that re-implemented the
  connection lifecycle would be testing the override, not the fix.

Note this file's client is a `TestClient` used as a context manager, unlike
every other client fixture here. That is load-bearing: a context-managed
`TestClient` holds one persistent portal/event loop for all requests, so
concurrent requests share one `run_in_threadpool` worker pool and genuinely
interleave across its threads. Without the context manager each request gets
its own event loop and its own single-threaded pool, which serializes the two
dispatches onto one thread and hides the bug.
"""

from __future__ import annotations

import importlib
import sqlite3
import threading
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import ModuleType

# `httpx2`, not `httpx`: both are installed, and starlette's `TestClient`
# prefers `httpx2` when present, so that is the `Response` type these
# helpers actually return (matching test_persona_narrate.py's import).
import httpx2
import pytest
from fastapi.testclient import TestClient
from fixtures.narrator_fake import FakeNarrator

FIXTURE_DB = Path(__file__).parent / "fixtures" / "cfb_verdict_fixture.sqlite3"

# One of the years `cfb_verdict_fixture.sqlite3` has real keener ratings for
# (see tests/conftest.py) -- so the verdict POST below exercises a full
# evidence build, not a 404 path that might never touch the connection.
FIXTURE_YEAR = 2005


def _api_deps() -> ModuleType:
    """The `api.deps` module object the routes actually use.

    Deliberately `importlib.import_module` and not `import api.deps as deps`:
    the latter reads the `deps` *attribute* of the `api` package, which
    `test_deps.py`'s reimport surgery can leave pointing at a different
    module object than `sys.modules["api.deps"]` -- and it is the
    `sys.modules` entry that every `from api.deps import get_db_conn` in a
    route module resolved to. Monkeypatching the wrong one of those two
    silently does nothing, so these tests would report a passing HTTP layer
    while reading the production db. `import_module` returns the
    `sys.modules` entry, so it always agrees with the routes.
    """
    return importlib.import_module("api.deps")


def _read_on_this_thread(conn: sqlite3.Connection) -> tuple[int, int]:
    """Run a trivial query and report which thread ran it."""
    row = conn.execute("SELECT COUNT(*) AS n FROM teams").fetchone()
    return threading.get_ident(), int(row["n"])


def test_get_db_conn_connection_is_usable_from_another_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The connection `get_db_conn` yields must survive being used by a
    thread other than the one that opened it -- the exact situation FastAPI
    creates when it dispatches the dependency and the route handler to the
    threadpool as two separate tasks.

    Fails pre-fix with `sqlite3.ProgrammingError` raised out of the worker
    thread (surfaced here by `Future.result()`).
    """
    deps = _api_deps()

    # `get_db_conn` looks `DB_PATH` up in its own module globals at call
    # time, so this redirects the real dependency at the fixture db without
    # reimplementing any of its lifecycle.
    monkeypatch.setattr(deps, "DB_PATH", FIXTURE_DB)

    gen = deps.get_db_conn()
    conn = next(gen)
    opened_on = threading.get_ident()
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            used_on, team_count = pool.submit(_read_on_this_thread, conn).result()
    finally:
        # Drives the dependency's own `finally: conn.close()`, on the
        # thread that opened it.
        gen.close()

    assert used_on != opened_on, "probe ran on the creating thread -- test proves nothing"
    assert team_count > 0


@pytest.fixture
def concurrent_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """A `TestClient` that uses the production `get_db_conn` unmodified,
    with only `DB_PATH` redirected at the fixture db.

    The persona dependencies are still overridden (an `InMemoryNarrationCache`
    and a stub narrator) so this test never opens Postgres or calls Claude,
    and `api.main.DATABASE_URL` is blanked because a context-managed
    `TestClient` runs `lifespan`, which would otherwise try to connect to a
    real Postgres instance on a developer machine with a populated `.env`.
    """
    import api.main
    from api.main import app
    from api.persona.cache import InMemoryNarrationCache

    deps = _api_deps()
    monkeypatch.setattr(deps, "DB_PATH", FIXTURE_DB)
    monkeypatch.setattr(api.main, "DATABASE_URL", "")

    app.dependency_overrides[deps.get_narration_cache] = lambda: InMemoryNarrationCache()
    app.dependency_overrides[deps.get_narrator] = lambda: FakeNarrator()
    try:
        # `raise_server_exceptions=False` so an unhandled exception comes
        # back as the HTTP 500 a real client would see, letting the
        # assertion report the same status codes the bug report did.
        with TestClient(app, raise_server_exceptions=False) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(deps.get_narration_cache, None)
        app.dependency_overrides.pop(deps.get_narrator, None)


def _get_years(client: TestClient) -> httpx2.Response:
    return client.get("/api/years")


def _get_teams(client: TestClient) -> httpx2.Response:
    return client.get("/api/teams", params={"year": FIXTURE_YEAR})


def _post_champion(client: TestClient) -> httpx2.Response:
    return client.post("/api/verdict/champion", json={"year": FIXTURE_YEAR})


# The three calls issue #94 fires together: remounting the corrected question
# form refetches the year and team catalogs while the verdict POST is in
# flight. Pre-fix this produced 500s the UI rendered as "Couldn't load the
# list of available years".
_CONCURRENT_CALLS: tuple[Callable[[TestClient], httpx2.Response], ...] = (
    _get_years,
    _get_teams,
    _post_champion,
)

_ROUNDS = 6


def test_concurrent_requests_never_return_500(concurrent_client: TestClient) -> None:
    """Every db-backed route must answer 200 when hit concurrently.

    Pre-fix this reports a mix of 200s and 500s (the reproducing probe on
    `main` saw `500 500 200 200` from four concurrent catalog GETs).
    """
    calls = [call for _ in range(_ROUNDS) for call in _CONCURRENT_CALLS]

    with ThreadPoolExecutor(max_workers=len(calls)) as pool:
        futures = [pool.submit(call, concurrent_client) for call in calls]
        responses = [future.result() for future in futures]

    statuses = [response.status_code for response in responses]
    failed = [
        (call.__name__, response.status_code, response.text[:200])
        for call, response in zip(calls, responses, strict=True)
        if response.status_code != 200
    ]
    assert not failed, f"concurrent requests returned non-200s: {failed} (all: {statuses})"
