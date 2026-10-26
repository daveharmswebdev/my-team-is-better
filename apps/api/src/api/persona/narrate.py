"""Per-call narration orchestration (issue #4; typed claims since issue #291,
epic #199 child 2 of 4).

The narrator answers with one forced `submit_narration` tool call
(`api.persona.claude_client`), which `api.persona.claims.check_and_render`
checks against the fact block and renders. What is served is always that
rendering, `ClaimOutcome.text`, never the narrator's raw `text` with its
placeholders. The budget is one call and at most one retry:

1. Call 1. Accepted: serve the rendered text.
2. Rejected with a tool call: replay the assistant content, then a user turn
   holding one `tool_result` for that tool_use id with `is_error: true` and
   the capped feedback. Rejected with no tool call: a user text turn with the
   capped feedback. Then call 2, checked the same way.
3. Rejected again: the templated fallback, logged with the same cap. Never a
   third call.

A Claude transport/API error on either call skips straight to the fallback
rather than raising, so a Claude outage degrades the narration, not the whole
verdict request.

**A refusal is not retried** (issue #463). The 5.x models can decline a
request with HTTP 200 and `stop_reason` "refusal" (with a
`stop_details.category` such as "cyber" or "general_harms"). Feedback can't
fix a policy decline, so a refused first call serves the fallback at once,
without a second call, and logs one warning naming the category when there
is one. A refusal on the retry serves the fallback too, logged the same way.

**The per-minute call budget** (issue #236). Each of the two calls first takes
one unit from the caller's `CallBudget` (`api.persona.budget`). A refused unit
means that call is never made and the fallback is served, logged once: before
call 1 because the budget is spent, and before call 2 because a rejected
first attempt is never served, so with no unit left for the retry the
fallback is the only grounded thing to give.

**The cap** (founder decision 2 on #291). The validator's errors are
unbounded: a text of 4,000 typed numbers gives 4,000 errors, 590,890
characters. `cap_feedback` keeps the first `MAX_FEEDBACK_ERRORS` in validator
order, then "…and N more errors", and the whole string is at most
`MAX_FEEDBACK_CHARS`, cut at an error boundary; a first error that alone
exceeds the budget is truncated to fit. The retry prompt and the fallback
warning both go through it, so neither grows with what the narrator submits.

`check_and_render` is the only grounding check there is. The lexical one that
read the finished prose was retired in #292, and nothing here matches numbers
or team names after the fact: a claim either resolves against the block or
becomes retry feedback.

Cache lookups happen one layer up, in `api.persona.service` -- this module
always makes at least one Claude call (or returns the fallback), never
inspects a cache itself. It does tell that caller whether it degraded to
the fallback (`NarrationResult.is_fallback`, issue #65), because a fallback
must not be cached as if it were a real narration.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass

import anthropic
from anthropic.types import MessageParam

from api.persona.budget import CallBudget
from api.persona.claims import TOOL_NAME, ClaimOutcome, check_and_render
from api.persona.claude_client import Narrator, NarratorReply
from api.persona.prompt import build_system_prompt, build_user_message
from api.repositories.teams import TeamRecord

logger = logging.getLogger(__name__)

# The SDK's own `max_retries` (default 2) already covers 429/5xx/connection
# retries transparently -- this is a separate, app-level concern: what to
# do once the SDK gives up (or a non-retryable APIStatusError comes back).
_TRANSPORT_ERRORS = (anthropic.APIStatusError, anthropic.APIConnectionError)

MAX_FEEDBACK_ERRORS = 10
MAX_FEEDBACK_CHARS = 8000

REJECTED_HEADER = "Rejected, nothing was shown to the user. Fix exactly these and submit again:"

# One `submit_narration` tool input in, the validator's verdict out.
ClaimCheck = Callable[[object], ClaimOutcome]


@dataclass(frozen=True)
class NarrationResult:
    """What `narrate()` served. `is_fallback` is true exactly when `text` is
    the caller's `fallback_text` because of a transport error on either call
    or two rejected submissions (issue #65), never for a real narration.
    """

    text: str
    is_fallback: bool


def cap_feedback(errors: Sequence[str], *, header: str) -> str:
    """`header`, then one "- error" line for each of the first
    `MAX_FEEDBACK_ERRORS` errors that fit, then "…and N more errors" for the
    rest, at most `MAX_FEEDBACK_CHARS` characters in all. It is cut at an
    error boundary, so an error is either shown whole or counted in N, except
    that a first error too long to fit on its own is truncated with "…"."""

    def build(shown: Sequence[str], hidden: int) -> str:
        lines = [header, *(f"- {error}" for error in shown)]
        if hidden:
            lines.append(f"…and {hidden} more error{'' if hidden == 1 else 's'}")
        return "\n".join(lines)

    total = len(errors)
    shown: list[str] = []
    for error in errors[:MAX_FEEDBACK_ERRORS]:
        if len(build([*shown, error], total - len(shown) - 1)) > MAX_FEEDBACK_CHARS:
            break
        shown.append(error)
    if not shown and errors:
        room = MAX_FEEDBACK_CHARS - len(build([""], total - 1))
        shown = [errors[0][: max(room - 1, 0)] + "…"]
    # Only a header longer than the whole budget could reach this slice.
    return build(shown, total - len(shown))[:MAX_FEEDBACK_CHARS]


def narrate(
    *,
    fact_block_json: str,
    user_team: str | None,
    contested: bool,
    catalog: Sequence[TeamRecord],
    narrator: Narrator,
    fallback_text: str,
    budget: CallBudget,
) -> NarrationResult:
    """Narrate `fact_block_json` in-character. `catalog` is the sport's full
    team catalog (`api.repositories.teams.list_team_records`), which the claim
    validator reads for names, mascots and aliases. Never raises for a Claude
    outage or a rejected submission: both degrade to `fallback_text`, with
    `is_fallback=True` so the caller knows not to cache it. Neither does a
    spent `budget`: a call it refuses is not made, and the result is the same
    fallback (issue #236).

    The team verdicts' entry point: the team prompt and the team claim check
    (`api.persona.claims.check_and_render`), run through `narrate_checked`.
    """
    return narrate_checked(
        system_prompt=build_system_prompt(user_team),
        user_message=build_user_message(fact_block_json, contested=contested),
        check=lambda tool_input: check_and_render(tool_input, fact_block_json, catalog),
        narrator=narrator,
        fallback_text=fallback_text,
        budget=budget,
    )


def narrate_checked(
    *,
    system_prompt: str,
    user_message: str,
    check: ClaimCheck,
    narrator: Narrator,
    fallback_text: str,
    budget: CallBudget,
) -> NarrationResult:
    """The one narration loop (module docstring), for any prompt and any
    claim check: `check` takes one `submit_narration` tool input and returns
    its `ClaimOutcome`. `narrate` runs the team verdicts through it and
    `api.persona.service.narrate_qb_comparison` the QB verdict (issue #451),
    so both share the budget, the two attempts, the capped retry feedback and
    the fallback."""
    messages: list[MessageParam] = [{"role": "user", "content": user_message}]
    fallback = NarrationResult(text=fallback_text, is_fallback=True)

    if not budget.try_acquire():
        logger.warning("Claude call budget spent, serving fallback narration without a call")
        return fallback
    try:
        first = narrator.submit(system=system_prompt, messages=list(messages))
    except _TRANSPORT_ERRORS as exc:
        logger.warning("Claude API call failed, serving fallback narration: %s", exc)
        return fallback

    if first.stop_reason == "refusal":
        _log_refusal(first, "serving fallback narration without a retry")
        return fallback

    first_outcome = _check(first, check)
    if first_outcome.text is not None:
        return NarrationResult(text=first_outcome.text, is_fallback=False)

    messages.extend(_retry_turns(first, first_outcome.errors))

    if not budget.try_acquire():
        logger.warning(
            "Claude call budget spent before the claim retry, serving fallback narration"
        )
        return fallback
    try:
        second = narrator.submit(system=system_prompt, messages=list(messages))
    except _TRANSPORT_ERRORS as exc:
        logger.warning("Claude API call failed on the claim retry, serving fallback: %s", exc)
        return fallback

    if second.stop_reason == "refusal":
        _log_refusal(second, "on the claim retry, serving fallback narration")
        return fallback

    second_outcome = _check(second, check)
    if second_outcome.text is not None:
        return NarrationResult(text=second_outcome.text, is_fallback=False)

    logger.warning(
        "%s",
        cap_feedback(
            second_outcome.errors,
            header=(
                f"Typed claims rejected twice ({len(first_outcome.errors)} errors on the first "
                "attempt); serving the templated fallback narration instead of a third Claude "
                "call. Retry errors:"
            ),
        ),
    )
    return fallback


def _log_refusal(reply: NarratorReply, what_next: str) -> None:
    category = f" (category {reply.refusal_category})" if reply.refusal_category is not None else ""
    logger.warning("Claude refused the narration%s; %s", category, what_next)


def _check(reply: NarratorReply, check: ClaimCheck) -> ClaimOutcome:
    """The validator's verdict on one reply; no tool call is a rejection."""
    if reply.tool_call is None:
        return ClaimOutcome(
            errors=(
                f"no {TOOL_NAME} call came back (stop reason: {reply.stop_reason}); answer "
                f"with exactly one {TOOL_NAME} call",
            ),
            text=None,
        )
    return check(reply.tool_call.input)


def _retry_turns(reply: NarratorReply, errors: Sequence[str]) -> list[MessageParam]:
    """The turns appended before the retry: the replayed assistant content and
    an `is_error` tool_result for its tool call, or, with no tool call to
    answer, a user text turn."""
    feedback = cap_feedback(errors, header=REJECTED_HEADER)
    if reply.tool_call is None:
        return [{"role": "user", "content": feedback}]
    return [
        {"role": "assistant", "content": list(reply.assistant_content)},
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": reply.tool_call.id,
                    "is_error": True,
                    "content": feedback,
                }
            ],
        },
    ]
