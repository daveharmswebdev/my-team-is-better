"""Failing-first test for `api.deps.list_all_team_names` (GitHub issue #13),
plus `get_narration_cache`/`get_narrator`'s `APP_TEST_MODE` seam (issue #39's
groundwork -- a real booted `uvicorn` process needs both to work with no live
Postgres instance or real `ANTHROPIC_API_KEY`).

Promoted out of `api.persona.service._all_team_names` (issue #4's grounding-
check helper) so both the persona grounding check and the new `/api/teams`
route call the same `SELECT DISTINCT school FROM teams` query -- see
`test_catalog.py` for the route-level coverage, and
`test_verdict_persona.py`'s existing grounding-mismatch tests (unchanged)
for proof the persona side still works correctly post-promotion.

The `APP_TEST_MODE` tests below reimport both `api.config` and `api.deps`
fresh after monkeypatching the environment -- mirrors `test_config.py`'s
`_reimport_config` pattern, since `api.deps` binds `DATABASE_URL`/
`APP_TEST_MODE` at import time via `from api.config import ...`.
"""

from __future__ import annotations

import importlib
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from cfb_strength.db.connection import get_conn

from api.deps import list_all_team_names

FIXTURE_DB = Path(__file__).parent / "fixtures" / "cfb_verdict_fixture.sqlite3"


def test_list_all_team_names_returns_real_teams_from_the_db() -> None:
    conn = get_conn(FIXTURE_DB, read_only=True)
    try:
        names = list_all_team_names(conn)
    finally:
        conn.close()

    assert "Texas" in names
    assert "USC" in names
    assert "Alabama" in names


def _reimport_deps() -> object:
    # `api.deps` binds `APP_TEST_MODE`/`DATABASE_URL` at import time, so a
    # stale `api.config` module (already imported with the old environment)
    # must be dropped too, or the reimported `api.deps` would still see the
    # old values.
    sys.modules.pop("api.config", None)
    sys.modules.pop("api.deps", None)
    return importlib.import_module("api.deps")


@pytest.fixture(autouse=True)
def _restore_api_deps_module() -> Iterator[None]:
    """Undoes `_reimport_deps`'s `sys.modules` surgery after each test in
    this file.

    `api.verdict` (imported once, early, and cached) binds
    `get_narration_cache`/`get_narrator` by *identity* at its own import
    time (`from api.deps import ...`), and FastAPI's
    `app.dependency_overrides` keys off that same identity. If a reimported
    `api.deps` module object were left in `sys.modules`, every later test's
    `client` fixture (`tests/conftest.py`) would import a *different*
    function object than the one `api.verdict`'s routes actually depend on,
    silently breaking its dependency overrides -- so this restores the
    original module objects (or absence thereof) once this test is done.
    """
    saved_config = sys.modules.get("api.config")
    saved_deps = sys.modules.get("api.deps")
    yield
    if saved_config is not None:
        sys.modules["api.config"] = saved_config
    else:
        sys.modules.pop("api.config", None)
    if saved_deps is not None:
        sys.modules["api.deps"] = saved_deps
    else:
        sys.modules.pop("api.deps", None)


def test_get_narration_cache_returns_in_memory_cache_in_test_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from api.persona.cache import InMemoryNarrationCache

    monkeypatch.setenv("APP_TEST_MODE", "1")
    monkeypatch.delenv("DATABASE_URL", raising=False)

    deps = _reimport_deps()
    cache = deps.get_narration_cache()  # type: ignore[attr-defined]

    assert isinstance(cache, InMemoryNarrationCache)


def test_get_narrator_returns_stub_narrator_in_test_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from api.persona.claude_client import StubNarrator

    monkeypatch.setenv("APP_TEST_MODE", "1")

    deps = _reimport_deps()
    narrator = deps.get_narrator()  # type: ignore[attr-defined]

    assert isinstance(narrator, StubNarrator)
    assert narrator.complete(system="", messages=[]) == "Solid case, no notes."


def test_get_narration_cache_still_raises_without_database_url_when_test_mode_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("APP_TEST_MODE", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    # Point the dotenv loader at a directory with no .env of its own, so this
    # test is safe on a machine that *does* have apps/api/.env populated with
    # a real DATABASE_URL (mirrors test_config.py's own equivalent test).
    monkeypatch.setenv("MY_TEAM_IS_BETTER_API_ENV_FILE", "/nonexistent/.env")

    deps = _reimport_deps()

    with pytest.raises(RuntimeError):
        deps.get_narration_cache()  # type: ignore[attr-defined]


def test_get_narrator_still_returns_claude_narrator_when_test_mode_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from api.persona.claude_client import ClaudeNarrator

    monkeypatch.delenv("APP_TEST_MODE", raising=False)

    deps = _reimport_deps()

    assert isinstance(deps.get_narrator(), ClaudeNarrator)  # type: ignore[attr-defined]
