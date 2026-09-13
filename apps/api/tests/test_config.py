"""Failing-first tests for `api.config` (issue #4).

`api.config` is this app's own `.env` loader -- deliberately not a reuse of
`cfb_strength.config`'s private `_load_dotenv` (that's the engine's internal
helper for its own `.env`, not part of the public evidence/db.connection
surface this app is scoped to). These tests never assert on the *real*
secret values in the gitignored `apps/api/.env` -- they monkeypatch the
environment before a fresh import, mirroring
`test_config_smoke.py`'s cwd-independence pattern for `cfb_strength.config`.
"""

from __future__ import annotations

import importlib
import sys

import pytest


def _reimport_config() -> object:
    sys.modules.pop("api.config", None)
    return importlib.import_module("api.config")


def test_config_reads_database_url_and_anthropic_key_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://fake-host/fake-db")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-fake-test-key")

    config = _reimport_config()

    assert config.DATABASE_URL == "postgresql://fake-host/fake-db"  # type: ignore[attr-defined]
    assert config.ANTHROPIC_API_KEY == "sk-fake-test-key"  # type: ignore[attr-defined]


def test_config_defaults_to_none_when_env_vars_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    # Point the dotenv loader at a directory with no .env of its own so this
    # test is safe on a machine that *does* have apps/api/.env populated.
    monkeypatch.setenv("MY_TEAM_IS_BETTER_API_ENV_FILE", "/nonexistent/.env")

    config = _reimport_config()

    assert config.DATABASE_URL is None  # type: ignore[attr-defined]
    assert config.ANTHROPIC_API_KEY is None  # type: ignore[attr-defined]


def test_config_exposes_prompt_version_string(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _reimport_config()

    assert isinstance(config.PROMPT_VERSION, str)  # type: ignore[attr-defined]
    assert config.PROMPT_VERSION  # type: ignore[attr-defined]


def test_prompt_version_is_past_the_tie_less_fact_blocks() -> None:
    """Issue #83 changed what Claude is given: every fact block now carries
    `ties`, and a tied game appears in `games` as `result: "T"` where it used
    to be dropped. Narrations cached under `persona-v1` were written from the
    old facts (the 2016 Bengals as 6-9, not 6-9-1), and the cache key includes
    this version, so it must have moved on for them to stop being served."""
    config = _reimport_config()

    assert config.PROMPT_VERSION != "persona-v1"  # type: ignore[attr-defined]


def test_prompt_version_is_past_the_method_less_compare_fact_blocks() -> None:
    """Issue #152 changed what the compare narrator is given: its fact block
    (`ComparisonResultOut.model_dump_json()`) now carries `method`. The cache
    key doesn't cover the fact block itself (#145), so narrations cached under
    `persona-v2` were written from method-less facts and would keep being
    served unless the version moves on."""
    config = _reimport_config()

    assert config.PROMPT_VERSION not in {"persona-v1", "persona-v2"}  # type: ignore[attr-defined]


def test_config_exposes_contested_years() -> None:
    config = _reimport_config()

    assert config.CONTESTED_YEARS == {2003, 2017}  # type: ignore[attr-defined]


def test_config_app_test_mode_true_only_for_exact_string_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_TEST_MODE", "1")

    config = _reimport_config()

    assert config.APP_TEST_MODE is True  # type: ignore[attr-defined]


def test_config_app_test_mode_defaults_to_false_when_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("APP_TEST_MODE", raising=False)

    config = _reimport_config()

    assert config.APP_TEST_MODE is False  # type: ignore[attr-defined]


def test_config_app_test_mode_false_for_non_one_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_TEST_MODE", "true")

    config = _reimport_config()

    assert config.APP_TEST_MODE is False  # type: ignore[attr-defined]
