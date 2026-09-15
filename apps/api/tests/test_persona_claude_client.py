"""Failing-first tests for `api.persona.claude_client`'s tool-call seam
(issue #291, epic #199 child 2 of 4).

`ClaudeNarrator` forces one `submit_narration` tool call and hands back what
`api.persona.narrate` needs: the tool_use block's id and raw input, the
assistant content to replay on a retry, and the stop reason. A fake
`anthropic` client captures the request kwargs, so nothing here reaches the
network or needs a key.

`StubNarrator` (APP_TEST_MODE=1) submits "Solid case, no notes." with no
claims; the Playwright e2e specs assert that exact served text
(`git grep "Solid case, no notes." apps/web/e2e`).
"""

from __future__ import annotations

from typing import Any, cast

import anthropic
from anthropic.types import ContentBlock, Message, TextBlock, ToolUseBlock, Usage
from fixtures.claim_blocks import cfb_catalog, cfb_comparison_block, cfb_team_case_block

from api.persona.claims import TOOL_NAME, check_and_render, tool_schema
from api.persona.claude_client import (
    MAX_TOKENS,
    MODEL,
    ClaudeNarrator,
    NarratorReply,
    StubNarrator,
    ToolCall,
)
from api.persona.narrate import NarrationResult, narrate

STUB_TEXT = "Solid case, no notes."
INPUT: dict[str, object] = {"text": "Look at {rec}.", "claims": []}


class _FakeMessages:
    def __init__(self, response: Message) -> None:
        self.response = response
        self.kwargs: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Message:
        self.kwargs.append(kwargs)
        return self.response


class _FakeAnthropic:
    def __init__(self, response: Message) -> None:
        self.messages = _FakeMessages(response)


def _message(content: list[ContentBlock], stop_reason: str = "tool_use") -> Message:
    return Message.model_validate(
        {
            "id": "msg_test",
            "type": "message",
            "role": "assistant",
            "model": MODEL,
            "content": [block.model_dump() for block in content],
            "stop_reason": stop_reason,
            "stop_sequence": None,
            "usage": Usage(input_tokens=10, output_tokens=20).model_dump(),
        }
    )


def _tool_use(tool_use_id: str = "toolu_1", name: str = TOOL_NAME) -> ToolUseBlock:
    return ToolUseBlock(id=tool_use_id, type="tool_use", name=name, input=dict(INPUT))


def _text(text: str) -> TextBlock:
    return TextBlock(type="text", text=text)


def _submit(
    content: list[ContentBlock], stop_reason: str = "tool_use"
) -> tuple[NarratorReply, dict[str, Any]]:
    fake = _FakeAnthropic(_message(content, stop_reason))
    narrator = ClaudeNarrator(cast(anthropic.Anthropic, fake))
    reply = narrator.submit(system="SYSTEM", messages=[{"role": "user", "content": "FACTS"}])
    (kwargs,) = fake.messages.kwargs
    return reply, kwargs


def test_the_model_and_token_budget() -> None:
    assert MODEL == "claude-haiku-4-5"
    assert MAX_TOKENS == 1200


def test_claude_narrator_forces_one_submit_narration_call_with_no_thinking() -> None:
    _, kwargs = _submit([_tool_use()])

    assert kwargs == {
        "model": "claude-haiku-4-5",
        "max_tokens": 1200,
        "system": "SYSTEM",
        "messages": [{"role": "user", "content": "FACTS"}],
        "tools": [tool_schema()],
        "tool_choice": {"type": "tool", "name": "submit_narration"},
    }


def test_the_reply_carries_the_tool_call_the_replay_content_and_the_stop_reason() -> None:
    reply, _ = _submit([_text("Here goes."), _tool_use("toolu_abc")])

    assert reply == NarratorReply(
        tool_call=ToolCall(id="toolu_abc", input=INPUT),
        assistant_content=(
            {"type": "text", "text": "Here goes."},
            {"type": "tool_use", "id": "toolu_abc", "name": TOOL_NAME, "input": INPUT},
        ),
        stop_reason="tool_use",
    )


def test_a_response_with_no_tool_use_block_is_a_reply_not_an_exception() -> None:
    reply, _ = _submit([_text("Texas 13-0.")], stop_reason="max_tokens")

    assert reply.tool_call is None
    assert reply.stop_reason == "max_tokens"
    assert reply.assistant_content == ({"type": "text", "text": "Texas 13-0."},)


def test_only_the_first_submit_narration_block_is_kept_and_replayed() -> None:
    # A replayed tool_use needs a tool_result in the next user turn, and the
    # retry answers exactly one, so no other tool_use block may be replayed.
    reply, _ = _submit(
        [
            _tool_use("toolu_other", name="something_else"),
            _tool_use("toolu_1"),
            _tool_use("toolu_2"),
        ]
    )

    assert reply.tool_call == ToolCall(id="toolu_1", input=INPUT)
    assert reply.assistant_content == (
        {"type": "tool_use", "id": "toolu_1", "name": TOOL_NAME, "input": INPUT},
    )


def test_stub_narrator_submits_the_fixed_line_with_no_claims() -> None:
    reply = StubNarrator().submit(system="", messages=[])

    assert reply.tool_call is not None
    assert reply.tool_call.input == {"text": STUB_TEXT, "claims": []}
    assert reply.assistant_content == (
        {
            "type": "tool_use",
            "id": reply.tool_call.id,
            "name": TOOL_NAME,
            "input": reply.tool_call.input,
        },
    )


def test_stub_narration_passes_the_claim_validator_on_real_blocks_verbatim() -> None:
    catalog = cfb_catalog()
    reply = StubNarrator().submit(system="", messages=[])
    assert reply.tool_call is not None
    for block in (
        cfb_team_case_block(2017, "Alabama"),
        cfb_comparison_block(2013, "Florida State", "Michigan State"),
    ):
        outcome = check_and_render(reply.tool_call.input, block, catalog)
        assert outcome.errors == ()
        assert outcome.text == STUB_TEXT
        served = narrate(
            fact_block_json=block,
            user_team=None,
            contested=False,
            catalog=catalog,
            narrator=StubNarrator(),
            fallback_text="the fallback",
        )
        assert served == NarrationResult(text=STUB_TEXT, is_fallback=False)
