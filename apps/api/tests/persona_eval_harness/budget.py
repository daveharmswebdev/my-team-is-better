"""The `--max-calls` budget: a worst-case estimate checked before a run, and
a hard cap enforced on every call during it.

**What a call is.** One logical call: one `Narrator.submit` or one grader
`messages.create`. The `anthropic` SDK retries a connection error, a 408,
409 or 429, or a 5xx on its own, up to `max_retries` (default 2) more HTTP
requests inside that one call, and the harness can't see them. So the cap
bounds logical calls, not HTTP requests: in the worst case the billed
requests reach three times the cap. The retry setting is left alone on
purpose, because the narrator is production's `ClaudeNarrator`. A call the
SDK gives up on still counts (it was spent before the call was made)."""

from __future__ import annotations

from typing import Literal

from anthropic.types import MessageParam

from api.persona.claude_client import Narrator, NarratorReply

# `api.persona.narrate`'s budget is one call and at most one retry, and each
# served narration gets one grader call.
NARRATOR_CALLS_PER_NARRATION = 2
GRADER_CALLS_PER_NARRATION = 1
WORST_CASE_CALLS_PER_NARRATION = NARRATOR_CALLS_PER_NARRATION + GRADER_CALLS_PER_NARRATION

CallKind = Literal["narrator", "grader"]


def worst_case_calls(*, cases: int, samples: int, variants: int) -> int:
    """The most logical Claude calls a run can make: cases x N x variants x 3
    (SDK-internal HTTP retries not included)."""
    return cases * samples * variants * WORST_CASE_CALLS_PER_NARRATION


class BudgetExhausted(Exception):
    """Raised instead of making a call past the cap. Not an
    `anthropic.APIError`, so production `narrate()` never swallows it into a
    fallback: it propagates to the runner, which stops."""


class CallBudget:
    """Counts logical Claude calls and refuses the one that would pass
    `max_calls`."""

    def __init__(self, max_calls: int) -> None:
        if max_calls < 0:
            raise ValueError(f"max_calls must be >= 0, got {max_calls}")
        self.max_calls = max_calls
        self.narrator_calls = 0
        self.grader_calls = 0

    @property
    def used(self) -> int:
        return self.narrator_calls + self.grader_calls

    def spend(self, kind: CallKind) -> None:
        """Account for one call about to be made, or raise `BudgetExhausted`
        without counting it."""
        if self.used >= self.max_calls:
            raise BudgetExhausted(
                f"the --max-calls cap of {self.max_calls} was reached "
                f"({self.narrator_calls} narrator + {self.grader_calls} grader calls)"
            )
        if kind == "narrator":
            self.narrator_calls += 1
        else:
            self.grader_calls += 1


class BudgetedNarrator:
    """Spends one narrator call from `budget` before every `submit`."""

    def __init__(self, inner: Narrator, budget: CallBudget) -> None:
        self._inner = inner
        self._budget = budget

    def submit(self, *, system: str, messages: list[MessageParam]) -> NarratorReply:
        self._budget.spend("narrator")
        return self._inner.submit(system=system, messages=messages)
