"""Failing-first tests for `api.persona.claude_client`'s per-model request
profiles (issue #463).

Three narrator models are supported, each with its own request shape:

- `claude-haiku-4-5` (production today): the forced `submit_narration` call,
  `max_tokens` 1200, no thinking, no effort -- byte-for-byte the request
  `tests/test_persona_claude_client.py` pins.
- `claude-haiku-5-5` and `claude-sonnet-5-5`: forced `tool_choice` is a 400
  on Sonnet 5.5 and skips thinking on Haiku 5.5, so both send
  `tool_choice: auto` with the tool exactly as haiku-4-5 sends it (no
  `strict` key since round B of #463), leave thinking at its adaptive
  default, send `output_config.effort` (medium unless overridden) and
  allow `max_tokens` 8000, since thinking counts toward it.

No profile ever sends `temperature`, `top_p`, `top_k` or `fallbacks`. A fake
`anthropic` client captures the request kwargs and hands back hand-built
`Message`s, so nothing here reaches the network or needs a key.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any, cast

import anthropic
import pytest
from anthropic.types import Message
from fixtures.claim_blocks import cfb_catalog, cfb_team_case_block

from api.config import QB_NARRATOR_MODEL, TEAM_NARRATOR_MODEL
from api.persona.budget import UnlimitedCallBudget
from api.persona.claims import TOOL_NAME, tool_schema
from api.persona.claude_client import (
    HAIKU_4_5,
    HAIKU_5_5,
    PROFILES,
    SONNET_5_5,
    SUPPORTED_MODELS,
    ClaudeNarrator,
    TokenUsage,
)
from api.persona.narrate import NarrationResult, narrate
from api.persona.qb_claims import qb_tool_schema

FORBIDDEN_KEYS = ("thinking", "temperature", "top_p", "top_k", "fallbacks")
FIVE_X = (HAIKU_5_5, SONNET_5_5)

TYPED_DIGITS: dict[str, object] = {"text": "They went 12-1 and nobody cared.", "claims": []}
GOOD: dict[str, object] = {
    "text": "Look at {rec} in {yr}.",
    "claims": [{"id": "rec", "kind": "record", "team": "Texas"}, {"id": "yr", "kind": "year"}],
}
GOOD_RENDERED = "Look at Texas 13-0 in 2005."


def _message(
    content: Sequence[dict[str, object]],
    *,
    stop_reason: str = "tool_use",
    model: str = SONNET_5_5,
    usage: dict[str, object] | None = None,
    stop_details: dict[str, object] | None = None,
) -> Message:
    return Message.model_validate(
        {
            "id": "msg_test",
            "type": "message",
            "role": "assistant",
            "model": model,
            "content": list(content),
            "stop_reason": stop_reason,
            "stop_details": stop_details,
            "stop_sequence": None,
            "usage": usage or {"input_tokens": 10, "output_tokens": 20},
        }
    )


def _tool_use(tool_input: dict[str, object], tool_use_id: str = "toolu_1") -> dict[str, object]:
    return {"type": "tool_use", "id": tool_use_id, "name": TOOL_NAME, "input": tool_input}


class _FakeMessages:
    def __init__(self, responses: Sequence[Message]) -> None:
        self._responses = list(responses)
        self.kwargs: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Message:
        self.kwargs.append(kwargs)
        assert self._responses, "the fake client ran out of scripted responses"
        return self._responses.pop(0)


class _FakeAnthropic:
    def __init__(self, *responses: Message) -> None:
        self.messages = _FakeMessages(responses)


def _kwargs_for(model: str, *, tool: dict[str, Any] | None = None, **extra: Any) -> dict[str, Any]:
    fake = _FakeAnthropic(_message([_tool_use(dict(GOOD))], model=model))
    narrator = ClaudeNarrator(cast(anthropic.Anthropic, fake), model=model, tool=tool, **extra)
    narrator.submit(system="SYSTEM", messages=[{"role": "user", "content": "FACTS"}])
    (kwargs,) = fake.messages.kwargs
    return kwargs


# ---------------------------------------------------------------------------
# the profiles
# ---------------------------------------------------------------------------


def test_exactly_three_models_are_supported_and_production_is_on_haiku_4_5() -> None:
    assert SUPPORTED_MODELS == ("claude-haiku-4-5", "claude-haiku-5-5", "claude-sonnet-5-5")
    assert set(PROFILES) == set(SUPPORTED_MODELS)
    assert TEAM_NARRATOR_MODEL == "claude-haiku-4-5"
    assert QB_NARRATOR_MODEL == "claude-haiku-4-5"


def test_haiku_4_5_sends_exactly_todays_request() -> None:
    assert _kwargs_for(HAIKU_4_5) == {
        "model": "claude-haiku-4-5",
        "max_tokens": 1200,
        "system": "SYSTEM",
        "messages": [{"role": "user", "content": "FACTS"}],
        "tools": [tool_schema()],
        "tool_choice": {"type": "tool", "name": "submit_narration"},
    }


@pytest.mark.parametrize("model", FIVE_X)
def test_a_5x_model_steers_with_auto_and_the_plain_tool(model: str) -> None:
    assert _kwargs_for(model) == {
        "model": model,
        "max_tokens": 8000,
        "system": "SYSTEM",
        "messages": [{"role": "user", "content": "FACTS"}],
        "tools": [tool_schema()],
        "tool_choice": {"type": "auto"},
        "output_config": {"effort": "medium"},
    }


@pytest.mark.parametrize("model", SUPPORTED_MODELS)
@pytest.mark.parametrize("tool", [None, qb_tool_schema()], ids=["team", "qb"])
def test_no_profile_sends_a_strict_tool(model: str, tool: dict[str, Any] | None) -> None:
    """Strict tool use malformed the 5.x models' margin claims (#463, measured
    live 2026-10-26), so no profile marks the tool strict, and the tool sent
    is the shared schema unchanged."""
    (sent,) = _kwargs_for(model, tool=tool)["tools"]
    assert "strict" not in sent
    assert sent == (tool_schema() if tool is None else qb_tool_schema())


@pytest.mark.parametrize("model", SUPPORTED_MODELS)
def test_no_profile_sends_thinking_sampling_or_fallbacks(model: str) -> None:
    kwargs = _kwargs_for(model)
    assert [key for key in FORBIDDEN_KEYS if key in kwargs] == []


@pytest.mark.parametrize("model", FIVE_X)
@pytest.mark.parametrize("effort", ["low", "medium", "high"])
def test_an_effort_override_reaches_a_5x_request(model: str, effort: str) -> None:
    assert _kwargs_for(model, effort=effort)["output_config"] == {"effort": effort}


def test_an_effort_override_on_haiku_4_5_is_a_value_error() -> None:
    with pytest.raises(ValueError, match="effort"):
        ClaudeNarrator(cast(anthropic.Anthropic, _FakeAnthropic()), model=HAIKU_4_5, effort="low")


@pytest.mark.parametrize("model", ["claude-haiku-4-5-20251001", "claude-opus-5", "", "gpt"])
def test_an_unknown_model_is_a_value_error_at_construction(model: str) -> None:
    with pytest.raises(ValueError, match="model"):
        ClaudeNarrator(cast(anthropic.Anthropic, _FakeAnthropic()), model=model)


def test_with_tool_keeps_the_model_or_takes_one() -> None:
    fake = cast(anthropic.Anthropic, _FakeAnthropic())
    team = ClaudeNarrator(fake, model=SONNET_5_5, effort="high")
    assert team.with_tool(qb_tool_schema()).model == SONNET_5_5
    assert team.with_tool(qb_tool_schema()).effort == "high"
    assert team.with_tool(qb_tool_schema(), model=HAIKU_5_5).model == HAIKU_5_5
    assert ClaudeNarrator(fake, model=HAIKU_4_5).with_tool(qb_tool_schema()).model == HAIKU_4_5


# ---------------------------------------------------------------------------
# the reply: usage, thinking replay, refusal
# ---------------------------------------------------------------------------


def test_the_reply_carries_the_usage_including_cache_tokens() -> None:
    fake = _FakeAnthropic(
        _message(
            [_tool_use(dict(GOOD))],
            usage={
                "input_tokens": 1000,
                "output_tokens": 200,
                "cache_creation_input_tokens": 400,
                "cache_read_input_tokens": 2000,
            },
        )
    )
    narrator = ClaudeNarrator(cast(anthropic.Anthropic, fake), model=SONNET_5_5)
    reply = narrator.submit(system="S", messages=[{"role": "user", "content": "F"}])
    assert reply.usage == TokenUsage(
        input_tokens=1000,
        output_tokens=200,
        cache_creation_input_tokens=400,
        cache_read_input_tokens=2000,
    )


def test_missing_cache_counts_read_as_zero() -> None:
    fake = _FakeAnthropic(_message([_tool_use(dict(GOOD))], model=HAIKU_4_5))
    reply = ClaudeNarrator(cast(anthropic.Anthropic, fake), model=HAIKU_4_5).submit(
        system="S", messages=[{"role": "user", "content": "F"}]
    )
    assert reply.usage == TokenUsage(
        input_tokens=10, output_tokens=20, cache_creation_input_tokens=0, cache_read_input_tokens=0
    )


def _narrate_texas(narrator: ClaudeNarrator) -> NarrationResult:
    return narrate(
        fact_block_json=cfb_team_case_block(2005, "Texas"),
        user_team=None,
        contested=False,
        catalog=cfb_catalog(),
        narrator=narrator,
        fallback_text="FALLBACK",
        budget=UnlimitedCallBudget(),
    )


@pytest.mark.parametrize("model", FIVE_X)
def test_the_claim_retry_replays_thinking_text_and_tool_use_in_order_unchanged(
    model: str,
) -> None:
    fake = _FakeAnthropic(
        _message(
            [
                {"type": "thinking", "thinking": "", "signature": "s1"},
                {"type": "text", "text": "Here goes."},
                _tool_use(dict(TYPED_DIGITS), "toolu_first"),
            ],
            model=model,
        ),
        _message([_tool_use(dict(GOOD), "toolu_second")], model=model),
    )
    result = _narrate_texas(ClaudeNarrator(cast(anthropic.Anthropic, fake), model=model))

    assert result == NarrationResult(text=GOOD_RENDERED, is_fallback=False)
    first, retry = fake.messages.kwargs
    assert retry["messages"][1] == {
        "role": "assistant",
        "content": [
            {"type": "thinking", "thinking": "", "signature": "s1"},
            {"type": "text", "text": "Here goes."},
            {"type": "tool_use", "id": "toolu_first", "name": TOOL_NAME, "input": TYPED_DIGITS},
        ],
    }
    # Append-only: the retry keeps the first call's system, tools and turns.
    assert retry["system"] == first["system"]
    assert retry["tools"] == first["tools"]
    assert retry["messages"][: len(first["messages"])] == first["messages"]
    assert {key: value for key, value in retry.items() if key != "messages"} == {
        key: value for key, value in first.items() if key != "messages"
    }


def test_a_redacted_thinking_block_is_replayed_unchanged() -> None:
    fake = _FakeAnthropic(
        _message(
            [
                {"type": "redacted_thinking", "data": "opaque-bytes"},
                {"type": "thinking", "thinking": "summary", "signature": "s2"},
                _tool_use(dict(TYPED_DIGITS), "toolu_first"),
            ]
        ),
        _message([_tool_use(dict(GOOD), "toolu_second")]),
    )
    _narrate_texas(ClaudeNarrator(cast(anthropic.Anthropic, fake), model=SONNET_5_5))
    _, retry = fake.messages.kwargs
    assert retry["messages"][1]["content"][:2] == [
        {"type": "redacted_thinking", "data": "opaque-bytes"},
        {"type": "thinking", "thinking": "summary", "signature": "s2"},
    ]


@pytest.mark.parametrize("category", ["cyber", None])
def test_a_refusal_serves_the_fallback_after_one_call_and_warns_once(
    category: str | None, caplog: pytest.LogCaptureFixture
) -> None:
    fake = _FakeAnthropic(
        _message(
            [],
            stop_reason="refusal",
            stop_details=None if category is None else {"type": "refusal", "category": category},
        )
    )
    narrator = ClaudeNarrator(cast(anthropic.Anthropic, fake), model=SONNET_5_5)
    with caplog.at_level(logging.WARNING, logger="api.persona.narrate"):
        result = _narrate_texas(narrator)

    assert result == NarrationResult(text="FALLBACK", is_fallback=True)
    assert len(fake.messages.kwargs) == 1
    warnings = [record for record in caplog.records if record.levelno >= logging.WARNING]
    assert len(warnings) == 1
    message = warnings[0].getMessage()
    assert "refus" in message
    if category is not None:
        assert category in message


def test_the_refusal_category_is_on_the_reply() -> None:
    fake = _FakeAnthropic(
        _message(
            [], stop_reason="refusal", stop_details={"type": "refusal", "category": "general_harms"}
        )
    )
    reply = ClaudeNarrator(cast(anthropic.Anthropic, fake), model=HAIKU_5_5).submit(
        system="S", messages=[{"role": "user", "content": "F"}]
    )
    assert reply.stop_reason == "refusal"
    assert reply.refusal_category == "general_harms"
    assert reply.tool_call is None


def test_a_refusal_on_the_retry_serves_the_fallback(caplog: pytest.LogCaptureFixture) -> None:
    fake = _FakeAnthropic(
        _message([_tool_use(dict(TYPED_DIGITS))]),
        _message([], stop_reason="refusal", stop_details={"type": "refusal", "category": "bio"}),
    )
    with caplog.at_level(logging.WARNING, logger="api.persona.narrate"):
        result = _narrate_texas(ClaudeNarrator(cast(anthropic.Anthropic, fake), model=SONNET_5_5))
    assert result == NarrationResult(text="FALLBACK", is_fallback=True)
    assert len(fake.messages.kwargs) == 2
    assert any("bio" in record.getMessage() for record in caplog.records)
