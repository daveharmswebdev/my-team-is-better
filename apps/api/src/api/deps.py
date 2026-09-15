"""FastAPI dependency wiring for the verdict routes.

Owns this app's database seam onto the engine: opening a read-only
`sqlite3.Connection` via `cfb_strength.db.connection.get_conn`, pointed at
`cfb_strength.config.DB_PATH`. Both of those imports are permitted by
docs/ARCHITECTURE.md §2's layering rule (apps/api may import
cfb_strength.evidence, cfb_strength.db, cfb_strength.contracts and
cfb_strength.config, and no other top-level engine module -- checked by
`apps/api/.importlinter` plus tests/test_import_layering_classification.py,
issue #54). No route imports `get_conn`/
`DB_PATH` directly -- they depend on `get_db_conn`, which tests override via
`app.dependency_overrides` to point at a fixture db instead (see
tests/conftest.py).

That connection is opened *non-strictly* (`check_same_thread=False`), which
is deliberate and must stay -- issue #44, an intermittent production HTTP
500 (`sqlite3.ProgrammingError: SQLite objects created in a thread can only
be used in that same thread`). FastAPI dispatches each sync callable in the
dependency-resolution chain to `run_in_threadpool` *independently*, so the
worker thread that runs this generator's `yield` is routinely not the one
the sync route body then uses the `Connection` on; sqlite's default
same-thread check rejects the second thread. Per-request connections were
already the right model -- only the strictness flag was wrong, so the fix is
that flag and not a pool, a lock, or `async def` routes. It is safe because
a connection opened here is closed in the same `finally` and therefore
belongs to exactly one logical request: two threads may touch it in
sequence, never at once. `cfb_strength.db.connection.get_conn` still
defaults to strict, which is correct for every single-threaded caller (CLI,
MCP server, tests), so this is the one place that opts out.
`tests/test_deps_threading.py` fails without the flag.

`get_narration_cache`/`get_narrator` (issue #4) follow the same override
pattern: every persona test replaces both with an `InMemoryNarrationCache`
and a fake `Narrator` via `app.dependency_overrides`, so the CI-safe test
suite never opens a real Postgres connection or calls the real Claude API.

Both also have a second, independent test-mode seam (issue #39's
groundwork): when `APP_TEST_MODE=1` (see `api.config`), `get_narration_cache`
returns an `InMemoryNarrationCache` instead of requiring `DATABASE_URL`/
building a `PostgresNarrationCache`, and `get_narrator` returns a
`StubNarrator` instead of a `ClaudeNarrator`. This is for a real *booted*
`uvicorn` process (e.g. the Playwright e2e job), which has no
`app.dependency_overrides` to lean on -- pytest's `TestClient`-based
overrides in `tests/conftest.py` are unaffected and unchanged by this flag.
When `APP_TEST_MODE` is false/unset, both functions behave exactly as
before, except that a missing `DATABASE_URL` no longer raises (issue #206):
`get_narration_cache` logs a warning and returns a `DisabledNarrationCache`,
so verdicts are served uncached instead of 500-ing.

This module is the dependency-injection wiring and nothing else. The two
team-name queries (`list_all_team_names`, issue #13, and
`list_team_records`, issue #78) lived here until issue #209 moved them to
`api.repositories.teams`, whose docstring explains why they are two queries:
`api.persona.service` importing them from here meant the persona layer
imported the module that builds the narrator and the cache *from* the
persona layer, an upward import that `.importlinter`'s `layers` contract
now forbids. Nothing is re-exported from here, so the old import path fails
loudly instead of quietly re-creating the cycle.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Iterator

from cfb_strength.config import DB_PATH
from cfb_strength.db.connection import get_conn

from api.config import APP_TEST_MODE, DATABASE_URL, PROMPT_VERSION
from api.persona.cache import (
    DisabledNarrationCache,
    InMemoryNarrationCache,
    NarrationCacheStore,
    PostgresNarrationCache,
)
from api.persona.claude_client import ClaudeNarrator, Narrator, StubNarrator

logger = logging.getLogger(__name__)


def get_db_conn() -> Iterator[sqlite3.Connection]:
    # `check_same_thread=False` (issue #44) is safe here, not merely
    # expedient, and the reason is specific to this function: it opens a
    # fresh connection per request and closes it in the same `finally`, so
    # each connection belongs to exactly one logical request and is never
    # used by two threads *at once* -- only, possibly, by two threads in
    # sequence, because FastAPI dispatches this sync generator dependency
    # and the sync route handler to `run_in_threadpool` independently.
    # Don't copy this flag to anything that shares a connection across
    # concurrent work: there it would hide a real bug instead of fixing one.
    conn = get_conn(DB_PATH, read_only=True, check_same_thread=False)
    try:
        yield conn
    finally:
        conn.close()


def get_narration_cache() -> NarrationCacheStore:
    if APP_TEST_MODE:
        return InMemoryNarrationCache()
    if not DATABASE_URL:
        # Issue #206: this used to raise, which 500'd every verdict route.
        # Availability beats the extra Claude calls, so serve uncached -- and
        # log it on every request, so a missing DATABASE_URL is never silent.
        logger.warning("DATABASE_URL is not configured -- persona narration cache disabled")
        return DisabledNarrationCache()
    return PostgresNarrationCache(DATABASE_URL, prompt_version=PROMPT_VERSION)


def get_narrator() -> Narrator:
    if APP_TEST_MODE:
        return StubNarrator()
    return ClaudeNarrator()
