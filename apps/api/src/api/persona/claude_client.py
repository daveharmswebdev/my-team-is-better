"""Thin, synchronous wrapper around the `anthropic` SDK for the persona
narration call (issue #4), which since issue #291 is one forced
`submit_narration` tool call (epic #199).

`Narrator` is the seam tests mock -- every CI-safe unit test injects a fake
implementing this `Protocol` instead of `ClaudeNarrator`, so the test suite
never hits the real Anthropic API. `ClaudeNarrator` is the real
implementation, used in production and in the key-gated integration test and
smoke eval.

Since #291 the seam returns the tool call, not text: a `NarratorReply` holds
the `submit_narration` tool_use block's id and raw input when there is one,
the assistant content `api.persona.narrate` replays before its `is_error`
tool_result on a retry, and the stop reason. A response with no such block is
a reply with `tool_call=None`, which `narrate` treats as a rejected attempt,
never an exception. The replay keeps only the text blocks and the first
`submit_narration` block: the retry answers exactly one tool_use id, and the
Messages API rejects a replayed tool_use left without its tool_result.

`StubNarrator` (issue #39's groundwork) is the production-code stand-in used
when `APP_TEST_MODE=1` (see `api.deps.get_narrator`): a real booted `uvicorn`
process (not pytest) needs a `Narrator` that never calls Anthropic. It
submits "Solid case, no notes." with no claims. That text has no numbers and
no team names, so `api.persona.claims.check_and_render` accepts it on any fact
block and it is served verbatim, never retried; the Playwright e2e specs in
apps/web/e2e assert that exact text.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, cast

import anthropic
from anthropic.types import (
    MessageParam,
    TextBlock,
    TextBlockParam,
    ToolParam,
    ToolUseBlock,
    ToolUseBlockParam,
)

from api.persona.claims import TOOL_NAME, tool_schema

# Exact model id per issue #4's brief -- verified against the current model
# catalog, no date suffix.
MODEL = "claude-haiku-4-5"

# The typed-claim spike's value (#200): a tool call carries the claims list as
# well as two or three sentences, and 27 spike calls averaged ~360 output
# tokens. Still a bound on a runaway generation.
MAX_TOKENS = 1200

STUB_NARRATION = "Solid case, no notes."

# The assistant content blocks a retry replays.
ReplayBlock = TextBlockParam | ToolUseBlockParam


@dataclass(frozen=True)
class ToolCall:
    """The `submit_narration` tool_use block: its `id`, which the retry's
    tool_result answers, and its raw `input`, which only
    `api.persona.claims.check_and_render` interprets."""

    id: str
    input: object


@dataclass(frozen=True)
class NarratorReply:
    """One narrator response. `tool_call` is `None` when the response held no
    `submit_narration` call; `assistant_content` is what to replay as the
    assistant turn before a retry; `stop_reason` is the API's."""

    tool_call: ToolCall | None
    assistant_content: tuple[ReplayBlock, ...]
    stop_reason: str | None


def tool_reply(
    tool_input: dict[str, object],
    *,
    tool_use_id: str = "toolu_stub",
    stop_reason: str = "tool_use",
) -> NarratorReply:
    """A reply holding one `submit_narration` call with `tool_input`, shaped
    exactly as `ClaudeNarrator` builds one from a real response."""
    block: ToolUseBlockParam = {
        "type": "tool_use",
        "id": tool_use_id,
        "name": TOOL_NAME,
        "input": tool_input,
    }
    return NarratorReply(
        tool_call=ToolCall(id=tool_use_id, input=tool_input),
        assistant_content=(block,),
        stop_reason=stop_reason,
    )


class Narrator(Protocol):
    def submit(self, *, system: str, messages: list[MessageParam]) -> NarratorReply: ...


class ClaudeNarrator:
    """Synchronous by design -- the `/api/verdict/*` routes are sync `def`
    FastAPI routes (FastAPI dispatches them onto a threadpool), so a
    blocking SDK call here is consistent with the existing pattern; no
    reason to introduce async just for this one call. `thinking` is
    intentionally omitted (Haiku 4.5 needs no extended thinking for a
    short narration task, and a forced `tool_choice` does not combine with
    it; omitting it is the documented default of no thinking).
    """

    def __init__(self, client: anthropic.Anthropic | None = None) -> None:
        # No explicit key -- resolves ANTHROPIC_API_KEY from the real
        # environment the normal way (issue #4's brief: never read the raw
        # value out of `.env` and pass it around by hand).
        self._client = client or anthropic.Anthropic()

    def submit(self, *, system: str, messages: list[MessageParam]) -> NarratorReply:
        response = self._client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=system,
            messages=messages,
            # `tool_schema()` is the Messages API tool shape, typed loosely in
            # `api.persona.claims`; `ToolParam` is the SDK's name for it.
            tools=[cast(ToolParam, tool_schema())],
            tool_choice={"type": "tool", "name": TOOL_NAME},
        )
        tool_call: ToolCall | None = None
        replay: list[ReplayBlock] = []
        for block in response.content:
            if isinstance(block, TextBlock):
                replay.append({"type": "text", "text": block.text})
            elif isinstance(block, ToolUseBlock) and block.name == TOOL_NAME and tool_call is None:
                tool_call = ToolCall(id=block.id, input=block.input)
                replay.append(
                    {"type": "tool_use", "id": block.id, "name": block.name, "input": block.input}
                )
        return NarratorReply(
            tool_call=tool_call,
            assistant_content=tuple(replay),
            stop_reason=response.stop_reason,
        )


class StubNarrator:
    """`APP_TEST_MODE=1` production stand-in for `ClaudeNarrator` -- never
    calls the real Anthropic API, never needs `ANTHROPIC_API_KEY`.
    """

    def submit(self, *, system: str, messages: list[MessageParam]) -> NarratorReply:
        return tool_reply({"text": STUB_NARRATION, "claims": []})
