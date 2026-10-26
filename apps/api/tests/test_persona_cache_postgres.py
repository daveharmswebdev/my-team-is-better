"""`PostgresNarrationCache` and `ensure_schema` against a real Postgres
(issue #210).

Every other cache test swaps `psycopg.connect` for a fake, so until now no
test had run the SQL production runs. These do, through the public entry
points only (`ensure_schema`, `PostgresNarrationCache.get`/`set`/
`with_prompt_version`), against the disposable database `TEST_DATABASE_URL`
names, each test in its own throwaway schema
(`tests/fixtures/postgres_scratch.py`). Without `TEST_DATABASE_URL` the
module skips; it never reads `DATABASE_URL`.

Reading rows back to check what was stored uses a plain `SELECT` on the
scratch schema: that is the assertion, not a copy of the code under test.
"""

from __future__ import annotations

import logging
import socket
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from cfb_strength.db.connection import get_conn
from cfb_strength.evidence.proof import build_team_case
from fastapi.testclient import TestClient
from fixtures.narrator_fake import FakeNarrator
from fixtures.postgres_scratch import (
    configured_test_database_url,
    requires_test_database,
    scratch_schema_dsn,
)
from psycopg.conninfo import make_conninfo

from api.config import PROMPT_VERSION, QB_PROMPT_VERSION, TEAM_NARRATOR_MODEL
from api.deps import get_narration_cache, get_narrator
from api.main import app
from api.models import TeamCaseOut
from api.persona.cache import (
    CachedNarration,
    PostgresNarrationCache,
    cache_key,
    ensure_schema,
)
from api.persona.claims import GROUNDING_VERSION
from api.persona.service import team_case_fact_block_json

pytestmark = requires_test_database

FIXTURE_DB = Path(__file__).parent / "fixtures" / "cfb_verdict_fixture.sqlite3"

EXPECTED_COLUMNS = [
    ("cache_key", "text", "NO"),
    ("narration_text", "text", "NO"),
    ("contested", "boolean", "NO"),
    ("prompt_version", "text", "NO"),
    ("created_at", "timestamp with time zone", "NO"),
]


@pytest.fixture
def scratch() -> Iterator[tuple[str, str]]:
    with scratch_schema_dsn() as (dsn, schema):
        yield dsn, schema


@pytest.fixture
def dsn(scratch: tuple[str, str]) -> str:
    """A scratch schema with `persona_cache` created by `ensure_schema`."""
    scratch_dsn, _ = scratch
    with psycopg.connect(scratch_dsn) as conn:
        ensure_schema(conn)
    return scratch_dsn


def _texas_2005_key() -> str:
    """The real key `narrate_team_case` computes for 2005's champion, from the
    fixture db's real fact block (as `test_verdict_persona_integration.py`)."""
    sqlite_conn = get_conn(FIXTURE_DB, read_only=True)
    try:
        case = TeamCaseOut.from_dataclass(
            build_team_case(sqlite_conn, 2005, "Texas", method="keener", sport="cfb")
        )
    finally:
        sqlite_conn.close()
    return cache_key(
        question_type="champion",
        year=2005,
        teams=("Texas",),
        user_team=None,
        method="keener",
        sport="cfb",
        prompt_version=PROMPT_VERSION,
        fact_block_json=team_case_fact_block_json(case),
        grounding_version=GROUNDING_VERSION,
        model=TEAM_NARRATOR_MODEL,
    )


def _columns(dsn: str, schema: str) -> list[tuple[str, str, str]]:
    with psycopg.connect(dsn) as conn:
        rows = conn.execute(
            "SELECT column_name, data_type, is_nullable FROM information_schema.columns"
            " WHERE table_schema = %s AND table_name = 'persona_cache'"
            " ORDER BY ordinal_position",
            (schema,),
        ).fetchall()
    return [(str(a), str(b), str(c)) for a, b, c in rows]


def _rows(dsn: str) -> list[tuple[str, str, bool, str]]:
    with psycopg.connect(dsn) as conn:
        rows = conn.execute(
            "SELECT cache_key, narration_text, contested, prompt_version"
            " FROM persona_cache ORDER BY cache_key"
        ).fetchall()
    return [(str(k), str(t), bool(c), str(v)) for k, t, c, v in rows]


def _api_warnings(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.levelno >= logging.WARNING and r.name.startswith("api")]


# ---------------------------------------------------------------------------
# ensure_schema
# ---------------------------------------------------------------------------


def test_ensure_schema_creates_the_table_and_is_idempotent(scratch: tuple[str, str]) -> None:
    scratch_dsn, schema = scratch
    assert _columns(scratch_dsn, schema) == []

    with psycopg.connect(scratch_dsn) as conn:
        ensure_schema(conn)
    assert _columns(scratch_dsn, schema) == EXPECTED_COLUMNS

    with psycopg.connect(scratch_dsn) as conn:
        ensure_schema(conn)  # second run: no error
        ensure_schema(conn)  # and on an already-used connection
    assert _columns(scratch_dsn, schema) == EXPECTED_COLUMNS


def test_ensure_schema_keeps_existing_rows(dsn: str) -> None:
    cache = PostgresNarrationCache(dsn, prompt_version="persona-test")
    cache.set("kept", CachedNarration(text="Still here.", contested=False))

    with psycopg.connect(dsn) as conn:
        ensure_schema(conn)

    assert cache.get("kept") == CachedNarration(text="Still here.", contested=False)


# ---------------------------------------------------------------------------
# get / set round trips
# ---------------------------------------------------------------------------


def test_miss_then_set_then_hit_with_a_real_cache_key(dsn: str) -> None:
    key = _texas_2005_key()
    cache = PostgresNarrationCache(dsn, prompt_version=PROMPT_VERSION)
    narration = CachedNarration(text="Texas, 2005. Vince did that.", contested=False)

    assert cache.get(key) is None
    cache.set(key, narration)

    assert cache.get(key) == narration
    # A second store on the same database (a later request) sees it too.
    assert PostgresNarrationCache(dsn, prompt_version=PROMPT_VERSION).get(key) == narration
    assert _rows(dsn) == [(key, narration.text, False, PROMPT_VERSION)]


def test_set_on_an_existing_key_overwrites_it(dsn: str) -> None:
    key = _texas_2005_key()
    old = PostgresNarrationCache(dsn, prompt_version="persona-old")
    new = PostgresNarrationCache(dsn, prompt_version="persona-new")

    old.set(key, CachedNarration(text="First take.", contested=False))
    new.set(key, CachedNarration(text="Second take.", contested=True))

    assert new.get(key) == CachedNarration(text="Second take.", contested=True)
    # One row, every column replaced (the upsert, not a second insert).
    assert _rows(dsn) == [(key, "Second take.", True, "persona-new")]


def test_overwrite_refreshes_created_at(dsn: str) -> None:
    cache = PostgresNarrationCache(dsn, prompt_version="persona-test")
    cache.set("k", CachedNarration(text="Old.", contested=False))
    with psycopg.connect(dsn) as conn:
        conn.execute(
            "UPDATE persona_cache SET created_at = now() - interval '30 days' WHERE cache_key = 'k'"
        )

    cache.set("k", CachedNarration(text="New.", contested=False))

    with psycopg.connect(dsn) as conn:
        row = conn.execute(
            "SELECT created_at > now() - interval '1 day' FROM persona_cache WHERE cache_key = 'k'"
        ).fetchone()
    assert row == (True,)


@pytest.mark.parametrize("contested", [True, False])
def test_contested_flag_round_trips(dsn: str, contested: bool) -> None:
    cache = PostgresNarrationCache(dsn, prompt_version="persona-test")
    cache.set("contested-key", CachedNarration(text="Coin flip.", contested=contested))

    hit = cache.get("contested-key")

    assert hit == CachedNarration(text="Coin flip.", contested=contested)
    assert hit is not None and hit.contested is contested


def test_prompt_version_label_is_stored_as_written(dsn: str) -> None:
    team = PostgresNarrationCache(dsn, prompt_version=PROMPT_VERSION)
    qb = team.with_prompt_version(QB_PROMPT_VERSION)
    odd = PostgresNarrationCache(dsn, prompt_version="Persona v13 -- ünïcode 'quoted'")

    team.set("a-team", CachedNarration(text="Team.", contested=False))
    qb.set("b-qb", CachedNarration(text="QB.", contested=False))
    odd.set("c-odd", CachedNarration(text="Odd.", contested=False))

    labels = {key: version for key, _, _, version in _rows(dsn)}
    assert labels == {
        "a-team": PROMPT_VERSION,
        "b-qb": QB_PROMPT_VERSION,
        "c-odd": "Persona v13 -- ünïcode 'quoted'",
    }


def test_narration_text_round_trips_byte_for_byte(dsn: str) -> None:
    text = 'It\'s 41-38.\nVince — 467 yards; "the" drive. 🏈 %s %(x)s \\ end'
    cache = PostgresNarrationCache(dsn, prompt_version="persona-test")
    cache.set("text-key", CachedNarration(text=text, contested=False))

    assert cache.get("text-key") == CachedNarration(text=text, contested=False)


def test_keys_are_independent(dsn: str) -> None:
    cache = PostgresNarrationCache(dsn, prompt_version="persona-test")
    cache.set("one", CachedNarration(text="One.", contested=False))

    assert cache.get("two") is None
    assert cache.get("one") == CachedNarration(text="One.", contested=False)


# ---------------------------------------------------------------------------
# The verdict route against the real store
# ---------------------------------------------------------------------------


def test_verdict_route_misses_then_hits_through_real_postgres(client: TestClient, dsn: str) -> None:
    narrator = FakeNarrator(["Texas. Next question."])
    app.dependency_overrides[get_narration_cache] = lambda: PostgresNarrationCache(
        dsn, prompt_version=PROMPT_VERSION
    )
    app.dependency_overrides[get_narrator] = lambda: narrator

    first = client.post("/api/verdict/champion", json={"year": 2005})
    second = client.post("/api/verdict/champion", json={"year": 2005})

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["narration"]["cached"] is False
    assert second.json()["narration"]["cached"] is True
    assert second.json()["narration"]["text"] == "Texas. Next question."
    assert len(narrator.calls) == 1
    # The route wrote exactly the key computed from the real fact block.
    assert _rows(dsn) == [(_texas_2005_key(), "Texas. Next question.", False, PROMPT_VERSION)]


# ---------------------------------------------------------------------------
# Issue #206's fail-open contract, against the real driver
# ---------------------------------------------------------------------------


def _closed_port() -> int:
    """A local port with nothing listening (bound, then released)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _assert_fails_open(cache: PostgresNarrationCache, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        assert cache.get("some-key") is None
    read_warnings = _api_warnings(caplog)
    assert len(read_warnings) == 1
    assert "treating as a miss" in read_warnings[0].getMessage()

    caplog.clear()
    with caplog.at_level(logging.WARNING):
        cache.set("some-key", CachedNarration(text="Lost.", contested=False))  # must not raise
    write_warnings = _api_warnings(caplog)
    assert len(write_warnings) == 1
    assert "not cached" in write_warnings[0].getMessage()


def test_unreachable_server_is_a_logged_miss_and_a_skipped_write(
    caplog: pytest.LogCaptureFixture,
) -> None:
    base = configured_test_database_url()
    assert base is not None
    closed = make_conninfo(base, host="127.0.0.1", port=str(_closed_port()))

    _assert_fails_open(PostgresNarrationCache(closed, prompt_version="persona-test"), caplog)


def test_server_refusing_the_connection_is_a_logged_miss_and_a_skipped_write(
    caplog: pytest.LogCaptureFixture,
) -> None:
    base = configured_test_database_url()
    assert base is not None
    missing_db = make_conninfo(base, dbname="t210_no_such_database")

    _assert_fails_open(PostgresNarrationCache(missing_db, prompt_version="persona-test"), caplog)


def test_missing_table_is_a_logged_miss_and_a_skipped_write(
    scratch: tuple[str, str], caplog: pytest.LogCaptureFixture
) -> None:
    """Postgres reachable, but `ensure_schema` never ran (startup's own
    schema setup failed): the real `UndefinedTable` error fails open too."""
    scratch_dsn, _ = scratch

    _assert_fails_open(PostgresNarrationCache(scratch_dsn, prompt_version="persona-test"), caplog)


def test_store_recovers_after_the_server_terminates_a_session(dsn: str) -> None:
    """A connection the server kills mid-session (a restart, an idle reaper)
    surfaces as a real `psycopg.OperationalError` on the next statement. The
    cache connects per call, so the store recovers on the next call."""
    cache = PostgresNarrationCache(dsn, prompt_version="persona-test")
    cache.set("k", CachedNarration(text="Kept.", contested=False))

    killed = psycopg.connect(dsn, autocommit=True)
    try:
        pid = killed.info.backend_pid
        with psycopg.connect(dsn, autocommit=True) as killer:
            killer.execute("SELECT pg_terminate_backend(%s)", (pid,))
        with pytest.raises(psycopg.OperationalError):
            killed.execute("SELECT 1")
    finally:
        killed.close()

    # The next call opens a fresh connection and still works.
    assert cache.get("k") == CachedNarration(text="Kept.", contested=False)
