"""The one `Narrator` test double for apps/api (issue #212).

Twenty near-identical doubles used to sit in twenty test files, each
re-deriving the same two behaviours: answer with a scripted reply, and record
the `system` and `messages` the call carried. `FakeNarrator` is now the only
one. It covers everything those twenty did:

* **no script** -- every call is answered with `ACCEPTED_NARRATION`, a
  claim-less submission the validator accepts against any fact block (no
  digits, no team names), so a test that only needs *some* narration in the
  envelope never has to know what a claim is;
* **a script** -- `FakeNarrator([...])`, one reply per call in order. A reply
  is a `submit_narration` tool input (`dict`), the text of a claim-less one
  (`str`), a whole `NarratorReply` (for the no-tool-call path), or an
  `Exception` to raise on that call (a Claude transport error). Running off
  the end of the script is an `AssertionError`, not a silent extra call;
* **one reply for every call** -- `FakeNarrator(always=...)`, for a narrator
  that always fails, or always answers without a tool call;
* **a reply computed from the call** -- `FakeNarrator(reply_for=...)`, for the
  eval harness, which answers by which fact block the call carried.

Every call is recorded as a `NarratorCall`, whose `messages` is a snapshot
taken at call time (production mutates the list it builds between calls, so a
live reference would read back the wrong thing). `NarratorCall.user_texts` and
`.retry_feedback` read a turn back without type-erasing: since #291 a
`MessageParam`'s content is either a string or a list of content blocks, and a
retry's feedback rides in an `is_error` `tool_result`.

Not production code. `api.persona.claude_client.StubNarrator` is the
`APP_TEST_MODE=1` production stand-in for a real booted uvicorn process and is
a different thing; never reach for it as a test fake. Not part of the pytest
suite itself either (this module doesn't match `test_*.py`) -- its own tests
are `tests/test_narrator_fake.py`.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from anthropic.types import MessageParam

from api.persona.claude_client import NarratorReply, tool_reply

ACCEPTED_NARRATION = "Solid case, no notes."
"""A submission the claim validator accepts against any fact block: no
digits, no proper-noun team names, no claims. Matches
`api.persona.claude_client.STUB_NARRATION` by intent, not by import -- a test
asserting on this text is asserting on the fake, not on production."""

Scripted = NarratorReply | Exception | dict[str, object] | str
"""What one scripted call may answer with. See the module docstring."""


def as_reply(scripted: NarratorReply | dict[str, object] | str) -> NarratorReply:
    """One scripted answer as the `NarratorReply` production would see.

    A `str` is the text of a claim-less submission; a `dict` is a whole
    `submit_narration` tool input; a `NarratorReply` is passed through, which
    is how a no-tool-call reply is scripted.
    """
    if isinstance(scripted, NarratorReply):
        return scripted
    if isinstance(scripted, str):
        return tool_reply({"text": scripted, "claims": []})
    return tool_reply(scripted)


def no_tool_reply(text: str = "Texas, easy.", *, stop_reason: str = "end_turn") -> NarratorReply:
    """A reply that held no `submit_narration` call, only prose --
    `api.persona.narrate` treats it as a rejected attempt, never an
    exception."""
    return NarratorReply(
        tool_call=None,
        assistant_content=({"type": "text", "text": text},),
        stop_reason=stop_reason,
    )


@dataclass(frozen=True)
class NarratorCall:
    """One recorded `submit`: the system prompt and the messages it carried."""

    system: str
    messages: list[MessageParam] = field(default_factory=list)

    @property
    def user_texts(self) -> tuple[str, ...]:
        """The text of every plain-string user turn, in order. A turn of
        content blocks (a replayed assistant turn, a `tool_result`) is not
        one."""
        return tuple(
            message["content"]
            for message in self.messages
            if message["role"] == "user" and isinstance(message["content"], str)
        )

    @property
    def retry_feedback(self) -> str | None:
        """The validator errors this call's last turn carried back to the
        narrator, or `None` on a first call. Either an `is_error` tool_result
        (the narrator did submit a tool call) or a plain user turn (it didn't).
        """
        if len(self.messages) < 2:
            return None
        content = self.messages[-1]["content"]
        if isinstance(content, str):
            return content
        (block,) = list(content)
        assert isinstance(block, dict), block
        feedback = dict(block)["content"]
        assert isinstance(feedback, str), feedback
        return feedback


class FakeNarrator:
    """A `Narrator` that answers from a script and records every call.

    Give at most one reply source: `replies` (one per call, in order),
    `always` (the same answer every call) or `reply_for` (computed from the
    call). With none, every call is answered with `ACCEPTED_NARRATION`.
    """

    def __init__(
        self,
        replies: Sequence[Scripted] | None = None,
        *,
        always: Scripted | None = None,
        reply_for: Callable[[NarratorCall], Scripted] | None = None,
    ) -> None:
        sources = [source for source in (replies, always, reply_for) if source is not None]
        assert len(sources) <= 1, (
            f"give exactly one reply source (replies, always or reply_for), got {len(sources)}"
        )
        self._replies: list[Scripted] | None = None if replies is None else list(replies)
        self._always = always
        self._reply_for = reply_for
        self.calls: list[NarratorCall] = []

    @property
    def systems(self) -> list[str]:
        """The system prompt of every call, in order."""
        return [call.system for call in self.calls]

    @property
    def messages(self) -> list[list[MessageParam]]:
        """The messages of every call, in order."""
        return [call.messages for call in self.calls]

    @property
    def pending(self) -> int:
        """Scripted replies not yet used, so a test can prove production
        stopped calling before the script ran out. Always 0 without a script.
        """
        return len(self._replies or ())

    def submit(self, *, system: str, messages: list[MessageParam]) -> NarratorReply:
        call = NarratorCall(system=system, messages=list(messages))
        self.calls.append(call)
        scripted = self._next(call)
        if isinstance(scripted, Exception):
            raise scripted
        return as_reply(scripted)

    def _next(self, call: NarratorCall) -> Scripted:
        if self._reply_for is not None:
            return self._reply_for(call)
        if self._always is not None:
            return self._always
        if self._replies is None:
            return {"text": ACCEPTED_NARRATION, "claims": []}
        assert self._replies, f"the narrator script ran out on call {len(self.calls)}"
        return self._replies.pop(0)
