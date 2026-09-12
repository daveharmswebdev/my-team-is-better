"""FastAPI dependency wiring for the verdict routes.

Owns this app's database seam onto the engine: opening a read-only
`sqlite3.Connection` via `cfb_strength.db.connection.get_conn`, pointed at
`cfb_strength.config.DB_PATH`. Both of those imports are permitted by
docs/ARCHITECTURE.md §2's layering rule (apps/api may import
cfb_strength.evidence, cfb_strength.db, cfb_strength.contracts and
cfb_strength.config, and must not import cfb_strength.ratings,
cfb_strength.ingest, cfb_strength.mcp_server or cfb_strength.cli -- checked
by `apps/api/.importlinter`, issue #54). No route imports `get_conn`/
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

`list_team_records` (issue #78) is the `/api/teams` route's *own* query,
deliberately not a `year` argument bolted onto `list_all_team_names`. The
two consumers want genuinely different things: the route wants the teams a
user can ask about for one season, with display metadata; the grounding
check wants the full team-name universe, because a persona response
mentioning a real-but-unrated opponent must still be recognized as a
team-name mention and checked against the fact block (narrowing it would
either flag legitimate opponents or silently accept invented ones). Two
functions keep that difference explicit instead of load-bearing on a
default argument.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass

from cfb_strength.config import DB_PATH
from cfb_strength.db.connection import get_conn

from api.config import APP_TEST_MODE, DATABASE_URL, PROMPT_VERSION
from api.persona.cache import InMemoryNarrationCache, NarrationCacheStore, PostgresNarrationCache
from api.persona.claude_client import ClaudeNarrator, Narrator, StubNarrator


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
        raise RuntimeError(
            "DATABASE_URL is not configured -- the persona response cache requires it"
        )
    return PostgresNarrationCache(DATABASE_URL, prompt_version=PROMPT_VERSION)


def get_narrator() -> Narrator:
    if APP_TEST_MODE:
        return StubNarrator()
    return ClaudeNarrator()


def list_all_team_names(conn: sqlite3.Connection, sport: str = "cfb") -> list[str]:
    """Every distinct team name in the db for `sport` -- deliberately *not*
    scoped to a particular year/method.

    Its consumer is the persona grounding check's "known team names"
    universe (`api.persona.service`), which needs every name the db knows
    about: a response that mentions a real-but-unrated opponent must still
    be recognized as a team-name mention and checked against the fact
    block. Issue #78 gave `/api/teams` its own year-scopable query
    (`list_team_records`) rather than adding a `year` argument here, so
    that this universe can never be narrowed by a picker-facing change.
    """
    rows = conn.execute("SELECT DISTINCT school FROM teams WHERE sport = ?", (sport,)).fetchall()
    return [str(row["school"]) for row in rows]


@dataclass(frozen=True)
class TeamRecord:
    """One selectable team: its canonical name plus the display/search
    metadata epic #76 added to `teams`.

    `name` is `teams.school` verbatim -- the string the client submits back
    and the one the verdict lookup, the persona grounding check, the golden
    dataset, and every cached narration key are keyed on. `mascot` is NULL
    for every NFL row (their `school` already carries city *and* nickname)
    and for any CFB team CFBD has no mascot for. `aliases` is the decoded
    `teams.alternate_names` JSON array, empty when the column is NULL or
    '[]' (both mean "no aliases known").
    """

    name: str
    mascot: str | None
    aliases: tuple[str, ...]


_TEAM_RECORD_COLUMNS = "t.school AS school, t.mascot AS mascot, t.alternate_names AS aliases_json"

# Ordered by `teams.id`, which is the rowid -- i.e. the same order an
# unordered full table scan already produced pre-#78, made explicit so the
# no-`year` response stays byte-identical (order included) rather than
# depending on the query planner.
_ALL_TEAM_RECORDS_SQL = f"""
SELECT {_TEAM_RECORD_COLUMNS}
FROM teams t
WHERE t.sport = ?
ORDER BY t.id
"""

# `ratings.sport` is filtered too, not just `teams.sport`: the join is on
# `team_id` alone, and a rating row carries its own sport, so checking both
# keeps the two columns from ever disagreeing about what a year means.
_RATED_TEAM_RECORDS_SQL = f"""
SELECT {_TEAM_RECORD_COLUMNS}
FROM teams t
JOIN ratings r ON r.team_id = t.id
WHERE t.sport = ? AND r.year = ? AND r.method = ? AND r.sport = ?
ORDER BY t.id
"""


def _decode_aliases(raw: object) -> tuple[str, ...]:
    """Decode a `teams.alternate_names` value into a tuple of alias
    strings. NULL, '[]', and anything that isn't a JSON array of strings
    all decode to empty -- this is display/search metadata populated by an
    ingest path `apps/api` doesn't own, so a malformed value degrades to
    "no aliases" rather than 500-ing a picker-population request.
    """
    if not isinstance(raw, str) or not raw.strip():
        return ()
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError:
        return ()
    if not isinstance(decoded, list):
        return ()
    return tuple(alias for alias in decoded if isinstance(alias, str) and alias)


def list_team_records(
    conn: sqlite3.Connection,
    sport: str = "cfb",
    year: int | None = None,
    method: str = "keener",
) -> list[TeamRecord]:
    """Selectable teams for `sport`, with display metadata -- the
    `/api/teams` route's query (see module docstring for why this is not
    `list_all_team_names` with an extra argument).

    With `year`, restricted to teams holding a `ratings` row for that
    `year`/`sport`/`method`: without it the nflverse ingest's one-row-per-
    historical-`team_abbr` model offers both halves of every relocation
    ("Las Vegas Raiders" for a 2010 question), and the CFB list offers the
    entire FBS/FCS/D2/D3 opponent universe the games ingest has ever seen.
    A year with no ratings at all is an empty list, not an error.

    Without `year`, this is exactly the pre-#78 `SELECT DISTINCT school FROM
    teams WHERE sport = ?` list, same names in the same order -- a client
    that never sends `year` sees no change.
    """
    if year is None:
        rows = conn.execute(_ALL_TEAM_RECORDS_SQL, (sport,)).fetchall()
    else:
        rows = conn.execute(_RATED_TEAM_RECORDS_SQL, (sport, year, method, sport)).fetchall()

    # Dedupe by name, first row wins -- preserves the pre-#78 query's
    # `DISTINCT school` semantics now that two more columns are selected
    # (two `teams` rows sharing a `school` within one sport must still
    # produce one entry, not two).
    records: dict[str, TeamRecord] = {}
    for row in rows:
        name = str(row["school"])
        if name in records:
            continue
        mascot = row["mascot"]
        records[name] = TeamRecord(
            name=name,
            mascot=str(mascot) if mascot is not None else None,
            aliases=_decode_aliases(row["aliases_json"]),
        )
    return list(records.values())
