"""`api.deps.get_qb_narrator` (issue #451): the QB route's narrator is the
app's narrator (`get_narrator`), sent with the QB tool instead of the team
one. A real `ClaudeNarrator` is rebuilt around the same client with
`qb_tool_schema()`; anything else (a test's `FakeNarrator`, the
`APP_TEST_MODE` `StubNarrator`) is passed through, so every override of
`get_narrator` covers the QB route too and no test can reach Claude through
it. A fake `anthropic` client captures the request: nothing here needs a key.
"""

from __future__ import annotations

from typing import Any, cast

import anthropic
from anthropic.types import Message, ToolUseBlock, Usage
from fixtures.narrator_fake import FakeNarrator

from api.deps import get_qb_narrator
from api.persona.claims import TOOL_NAME, tool_schema
from api.persona.claude_client import HAIKU_4_5, ClaudeNarrator, StubNarrator
from api.persona.qb_claims import qb_tool_schema


class _FakeMessages:
    def __init__(self) -> None:
        self.kwargs: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Message:
        self.kwargs.append(kwargs)
        block = ToolUseBlock(
            id="toolu_1", type="tool_use", name=TOOL_NAME, input={"text": "x", "claims": []}
        )
        return Message.model_validate(
            {
                "id": "msg_test",
                "type": "message",
                "role": "assistant",
                "model": HAIKU_4_5,
                "content": [block.model_dump()],
                "stop_reason": "tool_use",
                "stop_sequence": None,
                "usage": Usage(input_tokens=1, output_tokens=1).model_dump(),
            }
        )


class _FakeAnthropic:
    def __init__(self) -> None:
        self.messages = _FakeMessages()


def test_a_claude_narrator_is_sent_with_the_qb_tool() -> None:
    fake = _FakeAnthropic()
    team = ClaudeNarrator(cast(anthropic.Anthropic, fake), model=HAIKU_4_5)
    qb = get_qb_narrator(team)

    reply = qb.submit(system="S", messages=[{"role": "user", "content": "F"}])
    team.submit(system="S", messages=[{"role": "user", "content": "F"}])

    qb_kwargs, team_kwargs = fake.messages.kwargs
    assert qb_kwargs["tools"] == [qb_tool_schema()]
    assert qb_kwargs["tool_choice"] == {"type": "tool", "name": TOOL_NAME}
    assert reply.tool_call is not None
    # The team narrator it was built from is untouched.
    assert team_kwargs["tools"] == [tool_schema()]


def test_a_fake_or_stub_narrator_is_passed_through() -> None:
    fake = FakeNarrator()
    stub = StubNarrator()
    assert get_qb_narrator(fake) is fake
    assert get_qb_narrator(stub) is stub
