"""issue #4 §4.1's Postgres-backed persona response cache.

`NarrationCacheStore` is the small storage interface both implementations
satisfy structurally (a `Protocol`, no shared base class needed):
`PostgresNarrationCache` for production/the real integration test, and
`InMemoryNarrationCache` for the rest of the test suite -- which is what
lets the bulk of `apps/api`'s tests run with no live Postgres connection.

`ensure_schema` mirrors `cfb_strength.db.connection.ensure_schema`'s own
pattern (plain SQL, no migration framework) rather than pulling in Alembic
for one additive table.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import psycopg

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


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
) -> str:
    """issue #4's cache key: `hash(question_type, year, team(s), user_team,
    method, sport, PROMPT_VERSION)`. `teams` should be the evidence layer's
    *resolved* canonical name(s) (e.g. `TeamCaseOut.team_name`), not the raw
    request string, so cache hits survive e.g. "Bama" vs "Alabama" both
    resolving to the same team.

    `sport` is required with no default (issue #84): CFB and NFL share team
    names ("Houston", "Miami", "Arizona", ...), so without it a CFB question
    could be served the NFL narration for the same year/name/method, and
    keep being served it from the cache. Adding it changed every key, which
    invalidated all older entries on purpose, since they can't say which
    league they describe.
    """
    payload = {
        "question_type": question_type,
        "year": year,
        "teams": list(teams),
        "user_team": user_team,
        "method": method,
        "sport": sport,
        "prompt_version": prompt_version,
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


class PostgresNarrationCache:
    """Real `persona_cache`-table-backed `NarrationCacheStore`."""

    def __init__(self, dsn: str, *, prompt_version: str) -> None:
        self._dsn = dsn
        self._prompt_version = prompt_version

    def get(self, key: str) -> CachedNarration | None:
        with psycopg.connect(self._dsn) as conn:
            row = conn.execute(
                "SELECT narration_text, contested FROM persona_cache WHERE cache_key = %s",
                (key,),
            ).fetchone()
        if row is None:
            return None
        text, contested = row
        return CachedNarration(text=str(text), contested=bool(contested))

    def set(self, key: str, narration: CachedNarration) -> None:
        with psycopg.connect(self._dsn) as conn:
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
