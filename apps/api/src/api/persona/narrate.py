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

**The cap** (founder decision 2 on #291). The validator's errors are
unbounded: a text of 4,000 typed numbers gives 4,000 errors, 590,890
characters. `cap_feedback` keeps the first `MAX_FEEDBACK_ERRORS` in validator
order, then "…and N more errors", and the whole string is at most
`MAX_FEEDBACK_CHARS`, cut at an error boundary; a first error that alone
exceeds the budget is truncated to fit. The retry prompt and the fallback
warning both go through it, so neither grows with what the narrator submits.

Production no longer calls the lexical grounding check
(`api.persona.grounding`); #292 removes that module.

Cache lookups happen one layer up, in `api.persona.service` -- this module
always makes at least one Claude call (or returns the fallback), never
inspects a cache itself. It does tell that caller whether it degraded to
the fallback (`NarrationResult.is_fallback`, issue #65), because a fallback
must not be cached as if it were a real narration.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass

import anthropic
from anthropic.types import MessageParam

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
) -> NarrationResult:
    """Narrate `fact_block_json` in-character. `catalog` is the sport's full
    team catalog (`api.repositories.teams.list_team_records`), which the claim
    validator reads for names, mascots and aliases. Never raises for a Claude
    outage or a rejected submission: both degrade to `fallback_text`, with
    `is_fallback=True` so the caller knows not to cache it.
    """
    system_prompt = build_system_prompt(user_team)
    messages: list[MessageParam] = [
        {"role": "user", "content": build_user_message(fact_block_json, contested=contested)}
    ]
    fallback = NarrationResult(text=fallback_text, is_fallback=True)

    try:
        first = narrator.submit(system=system_prompt, messages=list(messages))
    except _TRANSPORT_ERRORS as exc:
        logger.warning("Claude API call failed, serving fallback narration: %s", exc)
        return fallback

    first_outcome = _check(first, fact_block_json, catalog)
    if first_outcome.text is not None:
        return NarrationResult(text=first_outcome.text, is_fallback=False)

    messages.extend(_retry_turns(first, first_outcome.errors))

    try:
        second = narrator.submit(system=system_prompt, messages=list(messages))
    except _TRANSPORT_ERRORS as exc:
        logger.warning("Claude API call failed on the claim retry, serving fallback: %s", exc)
        return fallback

    second_outcome = _check(second, fact_block_json, catalog)
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


def _check(
    reply: NarratorReply, fact_block_json: str, catalog: Sequence[TeamRecord]
) -> ClaimOutcome:
    """The validator's verdict on one reply; no tool call is a rejection."""
    if reply.tool_call is None:
        return ClaimOutcome(
            errors=(
                f"no {TOOL_NAME} call came back (stop reason: {reply.stop_reason}); answer "
                f"with exactly one {TOOL_NAME} call",
            ),
            text=None,
        )
    return check_and_render(reply.tool_call.input, fact_block_json, catalog)


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
