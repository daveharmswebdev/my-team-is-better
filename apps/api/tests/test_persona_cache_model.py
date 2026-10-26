"""Failing-first tests for the narrator model in the cache keys (issue #463),
and for the narrators `api.deps` builds.

`cache_key` and `qb_cache_key` take the narrator's model. It enters the
hashed payload only when it is not `claude-haiku-4-5`, the model every key
before #463 was written under, so every existing key is byte-identical: the
two digests below were computed at base 83f599d with these exact arguments,
before the model argument existed. A narration from another model gets a
key of its own.
"""

from __future__ import annotations

from typing import cast

import anthropic
import pytest

import api.deps as deps
from api.persona.cache import cache_key, qb_cache_key
from api.persona.claude_client import HAIKU_4_5, HAIKU_5_5, SONNET_5_5, ClaudeNarrator

# Computed at base 83f599d (no model argument then) with the arguments below.
BASE_TEAM_KEY = "5e33afcf5e1b575521e404330ba3efbb100443157d79f8a008c89b7892d7df33"
BASE_QB_KEY = "d315480d7e6db4a1e396d7288d7b0bcd7b6a620f241c8f85f34627cf2c7dfcbc"


def _team_key(model: str) -> str:
    return cache_key(
        question_type="compare",
        year=2013,
        teams=("Florida State", "Michigan State"),
        user_team=None,
        method="keener",
        sport="cfb",
        prompt_version="persona-v13",
        fact_block_json='{"pinned":true}',
        grounding_version="claims-v5",
        model=model,
    )


def _qb_key(model: str) -> str:
    return qb_cache_key(
        sport="nfl",
        a=2044124519,
        b=2385180619,
        qb_score_version="qb-score-v1",
        prompt_version="qb-persona-v2",
        fact_block_json='{"pinned":true}',
        grounding_version="qb-claims-v2",
        model=model,
    )


def test_haiku_4_5_keys_are_byte_identical_to_the_keys_before_the_model_argument() -> None:
    assert _team_key(HAIKU_4_5) == BASE_TEAM_KEY
    assert _qb_key(HAIKU_4_5) == BASE_QB_KEY


def test_each_5x_model_gets_keys_of_its_own() -> None:
    team = {_team_key(model) for model in (HAIKU_4_5, HAIKU_5_5, SONNET_5_5)}
    qb = {_qb_key(model) for model in (HAIKU_4_5, HAIKU_5_5, SONNET_5_5)}
    assert len(team) == 3
    assert len(qb) == 3
    assert team.isdisjoint(qb)


def _fake_client() -> anthropic.Anthropic:
    return cast(anthropic.Anthropic, object())


def test_get_narrator_builds_the_team_narrator_on_team_narrator_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(deps, "APP_TEST_MODE", False)
    monkeypatch.setattr(deps, "TEAM_NARRATOR_MODEL", SONNET_5_5)
    narrator = deps.get_narrator()
    assert isinstance(narrator, ClaudeNarrator)
    assert narrator.model == SONNET_5_5


def test_get_qb_narrator_builds_the_qb_narrator_on_qb_narrator_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(deps, "QB_NARRATOR_MODEL", HAIKU_5_5)
    team = ClaudeNarrator(_fake_client(), model=HAIKU_4_5)
    qb = deps.get_qb_narrator(team)
    assert isinstance(qb, ClaudeNarrator)
    assert qb.model == HAIKU_5_5
    assert team.model == HAIKU_4_5


def test_production_builds_both_narrators_on_haiku_4_5(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(deps, "APP_TEST_MODE", False)
    team = deps.get_narrator()
    qb = deps.get_qb_narrator(team)
    assert isinstance(team, ClaudeNarrator) and isinstance(qb, ClaudeNarrator)
    assert (team.model, qb.model) == (HAIKU_4_5, HAIKU_4_5)
