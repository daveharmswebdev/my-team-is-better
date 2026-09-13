"""Failing-first tests for `api.persona.cache` (issue #4 §4.1's Postgres
response cache). Only exercises the hash + the in-memory fake store here --
the real `PostgresNarrationCache` is covered by the gated integration test
in `tests/test_verdict_persona_integration.py`, not here, so this file
never needs a live Postgres connection.
"""

from __future__ import annotations

from api.persona.cache import CachedNarration, InMemoryNarrationCache, cache_key


def _key(**overrides: object) -> str:
    base: dict[str, object] = {
        "question_type": "team_case",
        "year": 2005,
        "teams": ("Texas",),
        "user_team": None,
        "method": "keener",
        "sport": "cfb",
        "prompt_version": "persona-v1",
    }
    base.update(overrides)
    return cache_key(**base)  # type: ignore[arg-type]


def test_cache_key_is_stable_for_identical_inputs() -> None:
    assert _key() == _key()


def test_cache_key_differs_by_question_type() -> None:
    assert _key(question_type="team_case") != _key(question_type="champion")


def test_cache_key_differs_by_year() -> None:
    assert _key(year=2005) != _key(year=2013)


def test_cache_key_differs_by_teams() -> None:
    assert _key(teams=("Texas",)) != _key(teams=("USC",))


def test_cache_key_differs_by_user_team() -> None:
    assert _key(user_team=None) != _key(user_team="Texas")


def test_cache_key_differs_by_method() -> None:
    assert _key(method="keener") != _key(method="colley")


def test_cache_key_differs_by_sport() -> None:
    # Issue #84: "Houston" (CFB) and "Houston" (NFL) for the same year and
    # method must never share a cached narration.
    assert _key(teams=("Houston",), sport="cfb") != _key(teams=("Houston",), sport="nfl")


def test_cache_key_differs_by_prompt_version() -> None:
    # This is the auto-bust-on-prompt-edit behavior issue #4 asks for.
    assert _key(prompt_version="persona-v1") != _key(prompt_version="persona-v2")


def test_in_memory_cache_miss_returns_none() -> None:
    cache = InMemoryNarrationCache()

    assert cache.get("nonexistent-key") is None


def test_in_memory_cache_set_then_get_round_trips() -> None:
    cache = InMemoryNarrationCache()
    narration = CachedNarration(text="Texas ran the table.", contested=False)

    cache.set("some-key", narration)

    assert cache.get("some-key") == narration
