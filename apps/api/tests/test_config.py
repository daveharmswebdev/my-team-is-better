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
    (`ComparisonResultOut.model_dump_json()`) now carries `method`. At the
    time the cache key did not cover the fact block (fixed in #145), so
    narrations cached under `persona-v2` were written from method-less facts
    and would have kept being served unless the version moved on."""
    config = _reimport_config()

    assert config.PROMPT_VERSION not in {"persona-v1", "persona-v2"}  # type: ignore[attr-defined]


def test_prompt_version_is_past_the_no_rating_rounding_prompt() -> None:
    """Issue #162 changed the system prompt itself: rule 1 now lets the
    narrator round a `rating` or `opponent_rating`. The cache key doesn't cover the prompt
    text, so narrations cached under `persona-v3` were written under the old
    "never round" rule and would keep being served unless the version moves."""
    config = _reimport_config()

    assert config.PROMPT_VERSION not in {  # type: ignore[attr-defined]
        "persona-v1",
        "persona-v2",
        "persona-v3",
    }


def test_prompt_version_is_past_the_no_keener_display_prompt() -> None:
    """Issue #165 changed the system prompt itself: rule 1 now tells the
    narrator a Keener rating may be quoted the way the site displays it
    (scaled and rounded, from `api.rating_display.RATING_DISPLAY`). The cache
    key doesn't cover the prompt text, so narrations cached under `persona-v4`
    were written without that rule and would keep being served unless the
    version moves."""
    config = _reimport_config()

    assert config.PROMPT_VERSION not in {  # type: ignore[attr-defined]
        "persona-v1",
        "persona-v2",
        "persona-v3",
        "persona-v4",
    }


def test_prompt_version_is_past_the_keener_display_prompt() -> None:
    """Issue #180 removed #165's Keener display sentence from rule 1: asked to
    scale a rating itself, claude-haiku-4-5 invented values ("5.47" for LSU
    2003's 4.73), and grounding served the templated fallback, which #65 then
    caches as if it were a real narration. Narrations cached under
    `persona-v5` include those fallbacks, so the version must move for them to
    stop being served."""
    config = _reimport_config()

    assert config.PROMPT_VERSION not in {  # type: ignore[attr-defined]
        "persona-v1",
        "persona-v2",
        "persona-v3",
        "persona-v4",
        "persona-v5",
    }


def test_prompt_version_is_past_the_argue_with_the_ranking_prompt() -> None:
    """Issue #231 changed the persona's attitude: the numbers are the numbers.
    persona-v6 served grounded narrations that argued against the ranking
    ("higher-rated on paper, but Texas already proved who shows up"). The
    cache key doesn't cover the prompt text, so narrations cached under
    `persona-v6` carry the old attitude and would keep being served unless the
    version moves."""
    config = _reimport_config()

    assert config.PROMPT_VERSION not in {  # type: ignore[attr-defined]
        "persona-v1",
        "persona-v2",
        "persona-v3",
        "persona-v4",
        "persona-v5",
        "persona-v6",
    }


def test_prompt_version_is_past_the_backwards_head_to_head_score() -> None:
    """Issue #122: the compare fact block's verdict printed the home score
    first after "X beat Y", so every away-team head-to-head win read backwards
    ("Seattle Seahawks beat Denver Broncos head-to-head 8-43"). Grounding
    checks narration against the fact block, so `persona-v7` narrations that
    repeated those scores were cached as grounded. At the time the cache key
    did not cover the fact block (fixed in #145), so the version had to move
    for them to stop being served."""
    config = _reimport_config()

    assert config.PROMPT_VERSION not in {  # type: ignore[attr-defined]
        "persona-v1",
        "persona-v2",
        "persona-v3",
        "persona-v4",
        "persona-v5",
        "persona-v6",
        "persona-v7",
    }


def test_prompt_version_is_past_the_last_meeting_only_common_opponents() -> None:
    """Issue #130 changed what the compare narrator is given: each
    `common_opponents` row now carries every meeting per side
    (`team_a_meetings` / `team_b_meetings`) instead of one result/score pair,
    and the engine's verdict prose lists them. At the time the cache key did
    not cover the fact block (fixed in #145: it now hashes the block, so a
    later change like this one misses on its own), so narrations cached under
    `persona-v8` were grounded against facts that hid earlier meetings and
    would have kept being served unless the version moved."""
    config = _reimport_config()

    assert config.PROMPT_VERSION not in {  # type: ignore[attr-defined]
        "persona-v1",
        "persona-v2",
        "persona-v3",
        "persona-v4",
        "persona-v5",
        "persona-v6",
        "persona-v7",
        "persona-v8",
    }


def test_prompt_version_is_past_the_losing_score_first_rule_5() -> None:
    """Issue #228 changed the system prompt itself: rule 5 used to demand
    `team_score` first for every score, so a loss had to read
    losing-score-first ("Florida got them 7-19"). It now says a loss
    winner-first with a loss cue ("lost 19-7 to Florida"). Since #145 the
    version means prompt wording only, and the wording changed, so
    narrations cached under `persona-v9` were written under the old rule and
    would keep being served unless the version moves."""
    config = _reimport_config()

    assert config.PROMPT_VERSION not in {  # type: ignore[attr-defined]
        "persona-v1",
        "persona-v2",
        "persona-v3",
        "persona-v4",
        "persona-v5",
        "persona-v6",
        "persona-v7",
        "persona-v8",
        "persona-v9",
    }


def test_prompt_version_is_past_the_typed_score_prompt() -> None:
    """Issue #291 changed the system prompt itself: the narrator no longer
    types numbers and has them checked by `api.persona.grounding`; it submits
    a `submit_narration` tool call whose placeholders the server renders from
    typed claims. Rule 1, rule 5 and the worked examples were rewritten, and
    the tool schema's description strings are prompt-facing too. Since #145
    the version means prompt wording only, and the wording changed, so
    narrations cached under `persona-v10` were written under the old rules and
    would keep being served unless the version moves (the cache key's
    grounding version moved too, to `claims-v1`)."""
    config = _reimport_config()

    assert config.PROMPT_VERSION == "persona-v11"  # type: ignore[attr-defined]  # _reimport_config() -> object


def test_config_exposes_contested_years() -> None:
    """Issue #151: contested years are per league. Only CFB has disputed
    seasons; the NFL entry is explicitly empty."""
    config = _reimport_config()

    assert config.CONTESTED_YEARS == {  # type: ignore[attr-defined]  # _reimport_config() -> object
        "cfb": frozenset({2003, 2017}),
        "nfl": frozenset(),
    }


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
