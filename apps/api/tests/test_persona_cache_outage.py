"""Issue #206: a Postgres problem degrades the persona narration cache, never
the verdict or the app.

The deterministic verdict is computed from SQLite; the Postgres cache only
saves a Claude call. So:

- a cache read that fails with a database error is a logged miss, and the
  request narrates normally (`cached=False`);
- a cache write that fails is logged, and the response is still returned;
- `PostgresNarrationCache` itself degrades the same way when it cannot
  connect, and every connect it makes carries a bounded `connect_timeout`, so
  an unreachable host fails fast instead of hanging on the OS TCP timeout;
- `main.lifespan`'s `ensure_schema` failing at startup is logged, and the app
  still serves `/health` and the catalog routes;
- the fail-open is narrow: only `psycopg.Error` is swallowed, so a programming
  bug in the cache path (here a `RuntimeError`) still surfaces.

Nothing here opens a real Postgres connection or calls Claude: stores are
fakes, and `psycopg.connect` is monkeypatched to raise or to hand back a fake
connection.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

import api.main as main_module
import api.persona.cache as cache_module
from api.deps import get_narration_cache, get_narrator
from api.main import app
from api.persona.cache import CachedNarration, PostgresNarrationCache

REAL_NARRATION = "Solid case, no notes."
READ_ERROR = "read side: server closed the connection unexpectedly"
WRITE_ERROR = "write side: could not connect to server"
FAKE_DSN = "postgresql://cache.invalid/persona"


class _ScriptedNarrator:
    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.calls = 0

    def complete(self, *, system: str, messages: list[dict[str, str]]) -> str:
        self.calls += 1
        return self.responses.pop(0)


class _FailingStore:
    """A `NarrationCacheStore` whose `get` and/or `set` raise a scripted
    exception; otherwise a working dict-backed store."""

    def __init__(
        self,
        *,
        get_error: BaseException | None = None,
        set_error: BaseException | None = None,
    ) -> None:
        self.get_error = get_error
        self.set_error = set_error
        self.store: dict[str, CachedNarration] = {}
        self.get_calls = 0
        self.set_calls = 0

    def get(self, key: str) -> CachedNarration | None:
        self.get_calls += 1
        if self.get_error is not None:
            raise self.get_error
        return self.store.get(key)

    def set(self, key: str, narration: CachedNarration) -> None:
        self.set_calls += 1
        if self.set_error is not None:
            raise self.set_error
        self.store[key] = narration


@contextmanager
def _wired(store: _FailingStore, narrator: _ScriptedNarrator) -> Iterator[None]:
    app.dependency_overrides[get_narration_cache] = lambda: store
    app.dependency_overrides[get_narrator] = lambda: narrator
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_narration_cache, None)
        app.dependency_overrides.pop(get_narrator, None)


def _api_warnings(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.levelno >= logging.WARNING and r.name.startswith("api")]


# ---------------------------------------------------------------------------
# (a)-(c): the verdict route survives a failing store
# ---------------------------------------------------------------------------


def test_cache_read_failure_is_a_logged_miss_and_the_verdict_still_narrates(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    store = _FailingStore(get_error=psycopg.OperationalError(READ_ERROR))
    narrator = _ScriptedNarrator([REAL_NARRATION])

    with _wired(store, narrator), caplog.at_level(logging.WARNING):
        response = client.post("/api/verdict/champion", json={"year": 2005})

    assert response.status_code == 200
    body = response.json()
    assert body["evidence"]["team_name"] == "Texas"
    assert body["narration"]["text"] == REAL_NARRATION
    assert body["narration"]["cached"] is False
    assert narrator.calls == 1
    # The write side is healthy, so the narration is still stored.
    assert list(store.store.values()) == [CachedNarration(text=REAL_NARRATION, contested=False)]
    warnings = _api_warnings(caplog)
    assert len(warnings) == 1
    assert READ_ERROR in warnings[0].getMessage()


def test_cache_write_failure_is_logged_and_the_verdict_is_still_returned(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    store = _FailingStore(set_error=psycopg.OperationalError(WRITE_ERROR))
    narrator = _ScriptedNarrator([REAL_NARRATION])

    with _wired(store, narrator), caplog.at_level(logging.WARNING):
        response = client.post("/api/verdict/champion", json={"year": 2005})

    assert response.status_code == 200
    body = response.json()
    assert body["narration"]["text"] == REAL_NARRATION
    assert body["narration"]["cached"] is False
    assert store.set_calls == 1
    warnings = _api_warnings(caplog)
    assert len(warnings) == 1
    assert WRITE_ERROR in warnings[0].getMessage()


def test_cache_read_and_write_both_failing_still_serves_the_verdict(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    store = _FailingStore(
        get_error=psycopg.OperationalError(READ_ERROR),
        set_error=psycopg.OperationalError(WRITE_ERROR),
    )
    narrator = _ScriptedNarrator([REAL_NARRATION])

    with _wired(store, narrator), caplog.at_level(logging.WARNING):
        response = client.post("/api/verdict/champion", json={"year": 2005})

    assert response.status_code == 200
    body = response.json()
    assert body["narration"]["text"] == REAL_NARRATION
    assert body["narration"]["cached"] is False
    messages = [r.getMessage() for r in _api_warnings(caplog)]
    assert len(messages) == 2
    assert READ_ERROR in messages[0]
    assert WRITE_ERROR in messages[1]


def test_healthy_store_still_serves_a_cached_hit(client: TestClient) -> None:
    store = _FailingStore()
    narrator = _ScriptedNarrator([REAL_NARRATION])

    with _wired(store, narrator):
        first = client.post("/api/verdict/champion", json={"year": 2005})
        second = client.post("/api/verdict/champion", json={"year": 2005})

    assert first.json()["narration"]["cached"] is False
    assert second.json()["narration"]["cached"] is True
    assert second.json()["narration"]["text"] == REAL_NARRATION
    assert narrator.calls == 1


# ---------------------------------------------------------------------------
# (f): the catch is narrow -- a non-database error still propagates
# ---------------------------------------------------------------------------


def test_non_database_error_from_cache_read_still_propagates(client: TestClient) -> None:
    store = _FailingStore(get_error=RuntimeError("a programming bug in the cache path"))
    narrator = _ScriptedNarrator([REAL_NARRATION])

    with _wired(store, narrator), pytest.raises(RuntimeError, match="programming bug"):
        client.post("/api/verdict/champion", json={"year": 2005})


def test_non_database_error_from_cache_write_still_propagates(client: TestClient) -> None:
    store = _FailingStore(set_error=RuntimeError("a programming bug in the cache path"))
    narrator = _ScriptedNarrator([REAL_NARRATION])

    with _wired(store, narrator), pytest.raises(RuntimeError, match="programming bug"):
        client.post("/api/verdict/champion", json={"year": 2005})


# ---------------------------------------------------------------------------
# (d), (e): PostgresNarrationCache itself
# ---------------------------------------------------------------------------


class _ConnectRecorder:
    """Stands in for `psycopg.connect`: records each call's kwargs, then
    raises `error` (default: an unreachable-host `OperationalError`)."""

    def __init__(self, error: BaseException | None = None) -> None:
        self.error = error if error is not None else psycopg.OperationalError("host unreachable")
        self.calls: list[dict[str, Any]] = []

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        raise self.error


def _narration() -> CachedNarration:
    return CachedNarration(text=REAL_NARRATION, contested=False)


def test_postgres_cache_get_is_a_logged_miss_when_postgres_is_unreachable(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(psycopg, "connect", _ConnectRecorder())
    cache = PostgresNarrationCache(FAKE_DSN, prompt_version="persona-test")

    with caplog.at_level(logging.WARNING):
        assert cache.get("some-key") is None

    warnings = _api_warnings(caplog)
    assert len(warnings) == 1
    assert "host unreachable" in warnings[0].getMessage()


def test_postgres_cache_set_is_logged_and_skipped_when_postgres_is_unreachable(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(psycopg, "connect", _ConnectRecorder())
    cache = PostgresNarrationCache(FAKE_DSN, prompt_version="persona-test")

    with caplog.at_level(logging.WARNING):
        cache.set("some-key", _narration())  # must not raise

    warnings = _api_warnings(caplog)
    assert len(warnings) == 1
    assert "host unreachable" in warnings[0].getMessage()


def test_postgres_cache_does_not_swallow_non_database_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(psycopg, "connect", _ConnectRecorder(RuntimeError("not a db error")))
    cache = PostgresNarrationCache(FAKE_DSN, prompt_version="persona-test")

    with pytest.raises(RuntimeError, match="not a db error"):
        cache.get("some-key")
    with pytest.raises(RuntimeError, match="not a db error"):
        cache.set("some-key", _narration())


def test_connect_timeout_is_a_few_seconds() -> None:
    timeout = cache_module.CONNECT_TIMEOUT_SECONDS
    assert isinstance(timeout, int)
    assert 1 <= timeout <= 10


def test_postgres_cache_get_and_set_pass_a_bounded_connect_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = _ConnectRecorder()
    monkeypatch.setattr(psycopg, "connect", recorder)
    cache = PostgresNarrationCache(FAKE_DSN, prompt_version="persona-test")

    # Suppressed so this test isolates the timeout from the fail-open above.
    with contextlib.suppress(psycopg.Error):
        cache.get("some-key")
    with contextlib.suppress(psycopg.Error):
        cache.set("some-key", _narration())

    assert len(recorder.calls) == 2
    for kwargs in recorder.calls:
        assert kwargs.get("connect_timeout") == cache_module.CONNECT_TIMEOUT_SECONDS


# ---------------------------------------------------------------------------
# lifespan: ensure_schema at startup
# ---------------------------------------------------------------------------


def test_app_starts_and_serves_when_ensure_schema_cannot_reach_postgres(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    recorder = _ConnectRecorder(psycopg.OperationalError("startup: host unreachable"))
    monkeypatch.setattr(psycopg, "connect", recorder)
    monkeypatch.setattr(main_module, "DATABASE_URL", FAKE_DSN)

    with caplog.at_level(logging.WARNING), client as started:
        years = started.get("/api/years")
        health = started.get("/health")

    assert years.status_code == 200
    assert health.status_code == 200
    assert len(recorder.calls) == 1
    assert recorder.calls[0].get("connect_timeout") == cache_module.CONNECT_TIMEOUT_SECONDS
    warnings = _api_warnings(caplog)
    assert len(warnings) == 1
    assert "startup: host unreachable" in warnings[0].getMessage()


class _FakeConn:
    def __enter__(self) -> _FakeConn:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


def test_healthy_lifespan_still_runs_ensure_schema_with_a_bounded_timeout(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    connect_kwargs: list[dict[str, Any]] = []
    schema_calls: list[object] = []
    fake_conn = _FakeConn()

    def _connect(*args: Any, **kwargs: Any) -> _FakeConn:
        connect_kwargs.append(kwargs)
        return fake_conn

    monkeypatch.setattr(psycopg, "connect", _connect)
    monkeypatch.setattr(main_module, "ensure_schema", schema_calls.append)
    monkeypatch.setattr(main_module, "DATABASE_URL", FAKE_DSN)

    with caplog.at_level(logging.WARNING), client as started:
        assert started.get("/health").status_code == 200

    assert schema_calls == [fake_conn]
    assert connect_kwargs == [{"connect_timeout": cache_module.CONNECT_TIMEOUT_SECONDS}]
    assert _api_warnings(caplog) == []
