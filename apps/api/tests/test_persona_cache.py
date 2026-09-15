"""Failing-first tests for `api.persona.cache` (issue #4 §4.1's Postgres
response cache). Only exercises the hash + the in-memory fake store here --
the real `PostgresNarrationCache` is covered by the gated integration test
in `tests/test_verdict_persona_integration.py`, not here, so this file
never needs a live Postgres connection.

The key covers the fact block and the grounding rules' version since issue
#145, so the fact blocks here are real ones from the committed fixture,
built with the service's own `comparison_fact_block_json` -- never a
hand-written string.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from cfb_strength.db.connection import get_conn
from cfb_strength.evidence.proof import build_comparison

from api.models import ComparisonResultOut
from api.persona.cache import CachedNarration, InMemoryNarrationCache, cache_key
from api.persona.service import comparison_fact_block_json

FIXTURE_DB = Path(__file__).parent / "fixtures" / "cfb_verdict_fixture.sqlite3"


@pytest.fixture(scope="module")
def comparison() -> Iterator[ComparisonResultOut]:
    conn: sqlite3.Connection = get_conn(FIXTURE_DB, read_only=True)
    try:
        yield ComparisonResultOut.from_dataclass(
            build_comparison(conn, 2005, "Texas", "USC", method="keener", sport="cfb")
        )
    finally:
        conn.close()


@pytest.fixture(scope="module")
def fact_block_json(comparison: ComparisonResultOut) -> str:
    return comparison_fact_block_json(comparison)


def _key(fact_block_json: str, **overrides: object) -> str:
    base: dict[str, object] = {
        "question_type": "team_case",
        "year": 2005,
        "teams": ("Texas",),
        "user_team": None,
        "method": "keener",
        "sport": "cfb",
        "prompt_version": "persona-v1",
        "fact_block_json": fact_block_json,
        "grounding_version": "grounding-v1",
    }
    base.update(overrides)
    return cache_key(**base)  # type: ignore[arg-type]


def test_cache_key_is_stable_for_identical_inputs(fact_block_json: str) -> None:
    assert _key(fact_block_json) == _key(fact_block_json)


def test_cache_key_differs_by_question_type(fact_block_json: str) -> None:
    assert _key(fact_block_json, question_type="team_case") != _key(
        fact_block_json, question_type="champion"
    )


def test_cache_key_differs_by_year(fact_block_json: str) -> None:
    assert _key(fact_block_json, year=2005) != _key(fact_block_json, year=2013)


def test_cache_key_differs_by_teams(fact_block_json: str) -> None:
    assert _key(fact_block_json, teams=("Texas",)) != _key(fact_block_json, teams=("USC",))


def test_cache_key_differs_by_user_team(fact_block_json: str) -> None:
    assert _key(fact_block_json, user_team=None) != _key(fact_block_json, user_team="Texas")


def test_cache_key_differs_by_method(fact_block_json: str) -> None:
    assert _key(fact_block_json, method="keener") != _key(fact_block_json, method="colley")


def test_cache_key_differs_by_sport(fact_block_json: str) -> None:
    # Issue #84: "Houston" (CFB) and "Houston" (NFL) for the same year and
    # method must never share a cached narration.
    assert _key(fact_block_json, teams=("Houston",), sport="cfb") != _key(
        fact_block_json, teams=("Houston",), sport="nfl"
    )


def test_cache_key_differs_by_prompt_version(fact_block_json: str) -> None:
    # This is the auto-bust-on-prompt-edit behavior issue #4 asks for.
    assert _key(fact_block_json, prompt_version="persona-v1") != _key(
        fact_block_json, prompt_version="persona-v2"
    )


def test_cache_key_differs_by_fact_block(comparison: ComparisonResultOut) -> None:
    """Issue #145: two blocks that differ only in the verdict's wording are
    two keys, so a narration generated from (and grounded against) one block
    is never served for the other."""
    reworded = comparison.model_copy(update={"verdict": comparison.verdict + " Barely."})
    original_json = comparison_fact_block_json(comparison)
    reworded_json = comparison_fact_block_json(reworded)
    assert original_json != reworded_json  # the change reached the block

    assert _key(original_json) != _key(reworded_json)


def test_cache_key_differs_by_grounding_version(fact_block_json: str) -> None:
    """Issue #145: a narration was checked under one set of grounding rules;
    tightening them must miss it, without touching PROMPT_VERSION."""
    assert _key(fact_block_json, grounding_version="grounding-v1") != _key(
        fact_block_json, grounding_version="grounding-v2"
    )


def test_cache_key_hashes_the_fact_block_rather_than_embedding_it(fact_block_json: str) -> None:
    """The key stays a fixed-length sha256 hex digest whatever the block's
    size; the block is folded in as its own sha256, not as raw text."""
    key = _key(fact_block_json)
    assert len(key) == 64
    assert all(c in "0123456789abcdef" for c in key)


def test_in_memory_cache_miss_returns_none() -> None:
    cache = InMemoryNarrationCache()

    assert cache.get("nonexistent-key") is None


def test_in_memory_cache_set_then_get_round_trips() -> None:
    cache = InMemoryNarrationCache()
    narration = CachedNarration(text="Texas ran the table.", contested=False)

    cache.set("some-key", narration)

    assert cache.get("some-key") == narration
