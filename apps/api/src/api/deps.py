"""FastAPI dependency wiring for the verdict routes.

Owns the single seam apps/api is allowed to cross per docs/ARCHITECTURE.md
§2: opening a read-only `sqlite3.Connection` via
`cfb_strength.db.connection.get_conn`, pointed at `cfb_strength.config.DB_PATH`.
No route imports `get_conn`/`DB_PATH` directly -- they depend on
`get_db_conn`, which tests override via `app.dependency_overrides` to point
at a fixture db instead (see tests/conftest.py).

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
before.

`list_all_team_names` (issue #13) is the shared "known team names" universe
-- originally a private helper on `api.persona.service` (issue #4's
grounding-check input), promoted here so `api.catalog`'s `/api/teams` route
and `api.persona.service`'s grounding check share one query rather than two
hand-maintained copies of `SELECT DISTINCT school FROM teams`.

Issue #59 scopes it by `sport` (default "cfb", matching every other call
site's default): CFB and NFL can share a team name (e.g. "Wildcats"), so an
unscoped universe would let a same-named team from the other sport
contaminate the persona grounding check's known-team-name membership test
for a case that was never about that team.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator

from cfb_strength.config import DB_PATH
from cfb_strength.db.connection import get_conn

from api.config import APP_TEST_MODE, DATABASE_URL, PROMPT_VERSION
from api.persona.cache import InMemoryNarrationCache, NarrationCacheStore, PostgresNarrationCache
from api.persona.claude_client import ClaudeNarrator, Narrator, StubNarrator


def get_db_conn() -> Iterator[sqlite3.Connection]:
    conn = get_conn(DB_PATH, read_only=True)
    try:
        yield conn
    finally:
        conn.close()


def get_narration_cache() -> NarrationCacheStore:
    if APP_TEST_MODE:
        return InMemoryNarrationCache()
    if not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL is not configured -- the persona response cache requires it"
        )
    return PostgresNarrationCache(DATABASE_URL, prompt_version=PROMPT_VERSION)


def get_narrator() -> Narrator:
    if APP_TEST_MODE:
        return StubNarrator()
    return ClaudeNarrator()


def list_all_team_names(conn: sqlite3.Connection, sport: str = "cfb") -> list[str]:
    """Every distinct team name in the db for `sport` -- not scoped to a
    particular year/method, since both this module's consumers (the persona
    grounding check's "known team names" universe, and `api.catalog`'s
    `/api/teams` route) want the full team-name universe for that sport, not
    a per-season subset.
    """
    rows = conn.execute("SELECT DISTINCT school FROM teams WHERE sport = ?", (sport,)).fetchall()
    return [str(row["school"]) for row in rows]
