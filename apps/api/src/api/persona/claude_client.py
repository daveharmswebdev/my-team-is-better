"""Thin, synchronous wrapper around the `anthropic` SDK for the persona
narration call (issue #4), which since issue #291 is one `submit_narration`
tool call (epic #199).

`Narrator` is the seam tests mock -- every CI-safe unit test injects a fake
implementing this `Protocol` instead of `ClaudeNarrator`, so the test suite
never hits the real Anthropic API. `ClaudeNarrator` is the real
implementation, used in production and in the key-gated integration test and
smoke eval.

Since #291 the seam returns the tool call, not text: a `NarratorReply` holds
the `submit_narration` tool_use block's id and raw input when there is one,
the assistant content `api.persona.narrate` replays before its `is_error`
tool_result on a retry, the stop reason, the refusal category (a
`stop_reason` of "refusal", #463), and the call's token usage (#463, so the
eval harness can cost a narration). A response with no such block is a
reply with `tool_call=None`, which `narrate` treats as a rejected attempt,
never an exception. The replay keeps the `thinking`, `redacted_thinking`
and text blocks, unchanged and in response order, and the first
`submit_narration` block: the retry answers exactly one tool_use id, and the
Messages API rejects a replayed tool_use left without its tool_result.

**Per-model request profiles (issue #463).** A `ClaudeNarrator` is built on
one of exactly three models (`PROFILES`); any other id is a `ValueError` at
construction. Production runs both narrators on `claude-haiku-4-5`
(`api.config.TEAM_NARRATOR_MODEL` / `QB_NARRATOR_MODEL`); the other two
exist so the eval harness can compare them by number before a switch.

- `claude-haiku-4-5`: the request production has sent since #291, byte for
  byte: `tool_choice` forces `submit_narration`, `max_tokens` 1200, no
  `thinking` and no `output_config` (this model has no adaptive thinking,
  and `effort` is an error on it).
- `claude-haiku-5-5` and `claude-sonnet-5-5`: forced `tool_choice`
  (`tool` or `any`) is a 400 on Sonnet 5.5, and on Haiku 5.5 it is accepted
  but the model then skips thinking. So both send `tool_choice: auto` with
  the tool marked `strict: true` (schema-valid arguments, the guarantee the
  forced call gave), and a reply with no `submit_narration` call is a
  rejected attempt that `narrate` retries with feedback, which it already
  was. Thinking is left at its adaptive default (no `thinking` field),
  `output_config.effort` is sent explicitly (`medium` unless the harness
  overrides it), and `max_tokens` is 8000 because thinking counts toward it.
  Both tool schemas (`api.persona.claims.tool_schema`,
  `api.persona.qb_claims.qb_tool_schema`) already meet the strict rules
  (`additionalProperties: false` and `required` on every object, no numeric
  or length constraints), so they are sent as they are plus `strict: true`,
  on a copy: haiku-4-5 never sees the flag.

No profile sends `temperature`, `top_p`, `top_k` (a 400 on the 5.x models)
or `fallbacks` (Haiku 5.5 has no server-side fallback, and a different
model's narration would not be the one being measured). The retry stays
append-only -- the same `system` and `tools`, only appended messages -- which
5.x thinking blocks require (a replayed block is checked against everything
before it).

`StubNarrator` (issue #39's groundwork) is the production-code stand-in used
when `APP_TEST_MODE=1` (see `api.deps.get_narrator`): a real booted `uvicorn`
process (not pytest) needs a `Narrator` that never calls Anthropic. It
submits "Solid case, no notes." with no claims. That text has no numbers and
no team names, so `api.persona.claims.check_and_render` accepts it on any fact
block and it is served verbatim, never retried; the Playwright e2e specs in
apps/web/e2e assert that exact text.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final, Literal, Protocol, cast

import anthropic
from anthropic.types import (
    Message,
    MessageParam,
    RedactedThinkingBlock,
    RedactedThinkingBlockParam,
    TextBlock,
    TextBlockParam,
    ThinkingBlock,
    ThinkingBlockParam,
    ToolUseBlock,
    ToolUseBlockParam,
    Usage,
)

from api.persona.claims import TOOL_NAME, tool_schema

# Exact model ids, no date suffix (issue #4's brief; #463 for the 5.x two).
HAIKU_4_5: Final = "claude-haiku-4-5"
HAIKU_5_5: Final = "claude-haiku-5-5"
SONNET_5_5: Final = "claude-sonnet-5-5"

# The effort levels a 5.x profile may be run at. `xhigh` and `max` exist too,
# but nothing here needs them.
Effort = Literal["low", "medium", "high"]
EFFORTS: Final[tuple[Effort, ...]] = ("low", "medium", "high")


@dataclass(frozen=True)
class RequestProfile:
    """How one model is asked for a narration (module docstring).
    `forced_tool` sends `tool_choice: {type: tool}`; otherwise the call is
    `tool_choice: auto` with a `strict` tool. `effort` is the
    `output_config.effort` sent by default, `None` for a model that takes no
    effort at all."""

    model: str
    max_tokens: int
    forced_tool: bool
    effort: Effort | None


PROFILES: Final[Mapping[str, RequestProfile]] = {
    # The typed-claim spike's value (#200): a tool call carries the claims
    # list as well as two or three sentences, and 27 spike calls averaged ~360
    # output tokens. Still a bound on a runaway generation.
    HAIKU_4_5: RequestProfile(HAIKU_4_5, max_tokens=1200, forced_tool=True, effort=None),
    # Thinking counts toward max_tokens, so these leave room for it.
    HAIKU_5_5: RequestProfile(HAIKU_5_5, max_tokens=8000, forced_tool=False, effort="medium"),
    SONNET_5_5: RequestProfile(SONNET_5_5, max_tokens=8000, forced_tool=False, effort="medium"),
}
SUPPORTED_MODELS: Final[tuple[str, ...]] = tuple(PROFILES)


def request_profile(model: str) -> RequestProfile:
    """The profile for `model`; any other id is a `ValueError`."""
    profile = PROFILES.get(model)
    if profile is None:
        raise ValueError(
            f"unsupported narrator model {model!r}; the supported models are {SUPPORTED_MODELS}"
        )
    return profile


STUB_NARRATION = "Solid case, no notes."

# The assistant content blocks a retry replays.
ReplayBlock = TextBlockParam | ToolUseBlockParam | ThinkingBlockParam | RedactedThinkingBlockParam


@dataclass(frozen=True)
class ToolCall:
    """The `submit_narration` tool_use block: its `id`, which the retry's
    tool_result answers, and its raw `input`, which only
    `api.persona.claims.check_and_render` interprets."""

    id: str
    input: object


@dataclass(frozen=True)
class TokenUsage:
    """One call's token counts, as the API bills them: `input_tokens` is the
    uncached input only; cache writes and reads are counted apart."""

    input_tokens: int
    output_tokens: int
    cache_creation_input_tokens: int
    cache_read_input_tokens: int

    @classmethod
    def from_sdk(cls, usage: Usage) -> TokenUsage:
        return cls(
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_creation_input_tokens=usage.cache_creation_input_tokens or 0,
            cache_read_input_tokens=usage.cache_read_input_tokens or 0,
        )


@dataclass(frozen=True)
class NarratorReply:
    """One narrator response. `tool_call` is `None` when the response held no
    `submit_narration` call; `assistant_content` is what to replay as the
    assistant turn before a retry; `stop_reason` is the API's. `usage` and
    `refusal_category` (`stop_details.category` on a "refusal") are `None`
    on a fake's reply and whenever the API gave none."""

    tool_call: ToolCall | None
    assistant_content: tuple[ReplayBlock, ...]
    stop_reason: str | None
    usage: TokenUsage | None = None
    refusal_category: str | None = None


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
    reason to introduce async just for this one call. What each `model` is
    sent is its `RequestProfile` (module docstring). `effort` overrides a
    5.x profile's default effort, and is a `ValueError` on
    `claude-haiku-4-5`, which takes none.
    """

    def __init__(
        self,
        client: anthropic.Anthropic | None = None,
        *,
        model: str,
        tool: dict[str, Any] | None = None,
        effort: Effort | None = None,
    ) -> None:
        self._profile = request_profile(model)
        if effort is not None:
            if self._profile.effort is None:
                raise ValueError(f"{model} takes no effort setting; got effort={effort!r}")
            if effort not in EFFORTS:
                raise ValueError(f"effort must be one of {EFFORTS}, got {effort!r}")
        self._effort: Effort | None = effort
        # No explicit key -- resolves ANTHROPIC_API_KEY from the real
        # environment the normal way (issue #4's brief: never read the raw
        # value out of `.env` and pass it around by hand).
        self._client = client or anthropic.Anthropic()
        # The `submit_narration` definition sent with every call: the team
        # verdicts' (`api.persona.claims.tool_schema`) unless one is given.
        # The QB verdict's (issue #451) has the same name and input shape but
        # its own claim kinds; `with_tool` builds that narrator.
        self._tool: dict[str, Any] = tool if tool is not None else tool_schema()

    @property
    def model(self) -> str:
        return self._profile.model

    @property
    def effort(self) -> Effort | None:
        """The effort override, `None` for the profile's default."""
        return self._effort

    def with_tool(self, tool: dict[str, Any], *, model: str | None = None) -> ClaudeNarrator:
        """A narrator on the same client that sends `tool` instead, on `model`
        when given and on this narrator's model otherwise. `tool` must be
        named `TOOL_NAME`: the reply is read back by that name."""
        if tool.get("name") != TOOL_NAME:
            raise ValueError(f"a narrator's tool must be named {TOOL_NAME!r}")
        return ClaudeNarrator(
            self._client, model=model or self.model, tool=tool, effort=self._effort
        )

    def request_kwargs(self, *, system: str, messages: list[MessageParam]) -> dict[str, Any]:
        """The `messages.create` arguments this narrator's profile sends."""
        profile = self._profile
        kwargs: dict[str, Any] = {
            "model": profile.model,
            "max_tokens": profile.max_tokens,
            "system": system,
            "messages": messages,
        }
        if profile.forced_tool:
            kwargs["tools"] = [self._tool]
            kwargs["tool_choice"] = {"type": "tool", "name": TOOL_NAME}
        else:
            # A copy: the shared schema dicts never carry the flag.
            kwargs["tools"] = [{**self._tool, "strict": True}]
            kwargs["tool_choice"] = {"type": "auto"}
        effort = self._effort or profile.effort
        if effort is not None:
            kwargs["output_config"] = {"effort": effort}
        return kwargs

    def submit(self, *, system: str, messages: list[MessageParam]) -> NarratorReply:
        # The tool schema is the Messages API tool shape, typed loosely in
        # `api.persona.claims`; the SDK's overloads take these kwargs as-is.
        response = cast(
            Message,
            self._client.messages.create(**self.request_kwargs(system=system, messages=messages)),
        )
        return reply_from_message(response)


def reply_from_message(response: Message) -> NarratorReply:
    """The `NarratorReply` for one API response. Blocks are read by type,
    never by position: a 5.x response can open with thinking blocks."""
    tool_call: ToolCall | None = None
    replay: list[ReplayBlock] = []
    for block in response.content:
        if isinstance(block, TextBlock):
            replay.append({"type": "text", "text": block.text})
        elif isinstance(block, ThinkingBlock):
            # Unchanged, signature and (often empty) text both: a modified
            # block is a 400.
            replay.append(
                {"type": "thinking", "thinking": block.thinking, "signature": block.signature}
            )
        elif isinstance(block, RedactedThinkingBlock):
            replay.append({"type": "redacted_thinking", "data": block.data})
        elif isinstance(block, ToolUseBlock) and block.name == TOOL_NAME and tool_call is None:
            tool_call = ToolCall(id=block.id, input=block.input)
            replay.append(
                {"type": "tool_use", "id": block.id, "name": block.name, "input": block.input}
            )
    details = response.stop_details
    return NarratorReply(
        tool_call=tool_call,
        assistant_content=tuple(replay),
        stop_reason=response.stop_reason,
        usage=TokenUsage.from_sdk(response.usage),
        refusal_category=None if details is None else details.category,
    )


class StubNarrator:
    """`APP_TEST_MODE=1` production stand-in for `ClaudeNarrator` -- never
    calls the real Anthropic API, never needs `ANTHROPIC_API_KEY`.
    """

    def submit(self, *, system: str, messages: list[MessageParam]) -> NarratorReply:
        return tool_reply({"text": STUB_NARRATION, "claims": []})
