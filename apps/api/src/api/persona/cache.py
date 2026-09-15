"""issue #4 §4.1's Postgres-backed persona response cache.

`NarrationCacheStore` is the small storage interface both implementations
satisfy structurally (a `Protocol`, no shared base class needed):
`PostgresNarrationCache` for production/the real integration test, and
`InMemoryNarrationCache` for the rest of the test suite -- which is what
lets the bulk of `apps/api`'s tests run with no live Postgres connection.

`ensure_schema` mirrors `cfb_strength.db.connection.ensure_schema`'s own
pattern (plain SQL, no migration framework) rather than pulling in Alembic
for one additive table.

**The cache is optional; the verdict is not (issue #206).** The verdict is
computed from SQLite, and this cache only saves a Claude call, so a Postgres
problem must never fail a request. `PostgresNarrationCache` treats a failed
read as a miss and a failed write as a skip, logging one warning each, and
every connect carries `CONNECT_TIMEOUT_SECONDS` so an unreachable host fails
fast instead of hanging a request on the OS TCP timeout. Only `psycopg.Error`
is swallowed: a programming bug in this path must still surface.
`DisabledNarrationCache` is the store served when `DATABASE_URL` is unset
outside test mode (see `api.deps.get_narration_cache`).
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import psycopg

logger = logging.getLogger(__name__)

SCHEMA_PATH = Path(__file__).with_name("schema.sql")

# libpq's `connect_timeout`, in seconds, for every Postgres connect this app
# makes (cache reads, cache writes, and `api.main.lifespan`'s schema setup).
# Short because a cache miss only costs one Claude call; a hung connect costs
# the whole request.
CONNECT_TIMEOUT_SECONDS = 3


@dataclass(frozen=True)
class CachedNarration:
    text: str
    contested: bool


class NarrationCacheStore(Protocol):
    def get(self, key: str) -> CachedNarration | None: ...

    def set(self, key: str, narration: CachedNarration) -> None: ...


def cache_key(
    *,
    question_type: str,
    year: int,
    teams: tuple[str, ...],
    user_team: str | None,
    method: str,
    sport: str,
    prompt_version: str,
    fact_block_json: str,
    grounding_version: str,
) -> str:
    """issue #4's cache key: `hash(question_type, year, team(s), user_team,
    method, sport, PROMPT_VERSION, sha256(fact block), GROUNDING_VERSION)`.
    `teams` should be the evidence layer's *resolved* canonical name(s)
    (e.g. `TeamCaseOut.team_name`), not the raw request string, so cache
    hits survive e.g. "Bama" vs "Alabama" both resolving to the same team.

    `sport` is required with no default (issue #84): CFB and NFL share team
    names ("Houston", "Miami", "Arizona", ...), so without it a CFB question
    could be served the NFL narration for the same year/name/method, and
    keep being served it from the cache. Adding it changed every key, which
    invalidated all older entries on purpose, since they can't say which
    league they describe.

    `fact_block_json` and `grounding_version` (issue #145): a cached
    narration was generated from one exact fact block and passed the
    grounding check under one set of rules, and the key says which. Before
    #145 it did not, so every change to the block -- a new field (#83,
    #152, #130), a corrected score (#122) -- had to be paid for with a
    `PROMPT_VERSION` bump that discarded every narration in both leagues,
    and a tightening of the grounding rules could invalidate nothing at all.
    `fact_block_json` is the canonical block string the narrator and the
    checker see (`api.persona.service.team_case_fact_block_json` /
    `comparison_fact_block_json`, never a bare `model_dump_json()`); it is
    folded in as its own sha256 rather than as text, so the key stays one
    fixed-length digest whatever the block's size. `grounding_version` is
    `api.persona.claims.GROUNDING_VERSION`, the typed-claim validator's
    (issue #291; `api.persona.grounding`'s before). A changed block, or tightened
    rules, now miss exactly the affected entries, and `PROMPT_VERSION` is
    back to meaning the prompt wording changed. Adding these two fields
    changed every key, which invalidated all older entries on purpose (the
    same deliberate bust #84 did): they cannot say which block they were
    written from.
    """
    payload = {
        "question_type": question_type,
        "year": year,
        "teams": list(teams),
        "user_team": user_team,
        "method": method,
        "sport": sport,
        "prompt_version": prompt_version,
        "fact_block_sha256": hashlib.sha256(fact_block_json.encode("utf-8")).hexdigest(),
        "grounding_version": grounding_version,
    }
    canonical = json.dumps(payload, sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class InMemoryNarrationCache:
    """Dict-backed fake `NarrationCacheStore` -- the CI-safe unit test
    suite's only cache implementation; no live Postgres connection needed.
    """

    def __init__(self) -> None:
        self._store: dict[str, CachedNarration] = {}

    def get(self, key: str) -> CachedNarration | None:
        return self._store.get(key)

    def set(self, key: str, narration: CachedNarration) -> None:
        self._store[key] = narration


class DisabledNarrationCache:
    """A `NarrationCacheStore` that never hits: every `get` is a miss and
    `set` does nothing. Served when no `DATABASE_URL` is configured outside
    test mode (issue #206), so verdicts still narrate, just uncached."""

    def get(self, key: str) -> CachedNarration | None:
        return None

    def set(self, key: str, narration: CachedNarration) -> None:
        return None


class PostgresNarrationCache:
    """Real `persona_cache`-table-backed `NarrationCacheStore`. Fails open on
    database errors (see the module docstring, issue #206)."""

    def __init__(self, dsn: str, *, prompt_version: str) -> None:
        self._dsn = dsn
        self._prompt_version = prompt_version

    def get(self, key: str) -> CachedNarration | None:
        try:
            with psycopg.connect(self._dsn, connect_timeout=CONNECT_TIMEOUT_SECONDS) as conn:
                row = conn.execute(
                    "SELECT narration_text, contested FROM persona_cache WHERE cache_key = %s",
                    (key,),
                ).fetchone()
        except psycopg.Error as exc:
            logger.warning("Narration cache read failed, treating as a miss: %s", exc)
            return None
        if row is None:
            return None
        text, contested = row
        return CachedNarration(text=str(text), contested=bool(contested))

    def set(self, key: str, narration: CachedNarration) -> None:
        try:
            with psycopg.connect(self._dsn, connect_timeout=CONNECT_TIMEOUT_SECONDS) as conn:
                conn.execute(
                    """
                    INSERT INTO persona_cache (cache_key, narration_text, contested, prompt_version)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (cache_key) DO UPDATE SET
                        narration_text = EXCLUDED.narration_text,
                        contested = EXCLUDED.contested,
                        prompt_version = EXCLUDED.prompt_version,
                        created_at = now()
                    """,
                    (key, narration.text, narration.contested, self._prompt_version),
                )
                conn.commit()
        except psycopg.Error as exc:
            logger.warning("Narration cache write failed, narration not cached: %s", exc)


def ensure_schema(conn: psycopg.Connection[Any]) -> None:
    """Idempotent `persona_cache` table setup. Split on `;` and executed
    statement-by-statement rather than as one `conn.execute(...)` call --
    psycopg3's extended query protocol (unlike psycopg2's simple query
    protocol) only supports one statement per `execute()`.
    """
    for statement in SCHEMA_PATH.read_text().split(";"):
        statement = statement.strip()
        if statement:
            conn.execute(statement)
    conn.commit()
