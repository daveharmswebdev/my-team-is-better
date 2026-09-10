"""issue #4's per-call narration orchestration: one Claude call, a
post-generation grounding check, exactly one retry with the specific
mismatch fed back, and a templated fallback after two failures
(Architecture Brief §4.3). A Claude transport/API error is treated the
same as a second grounding failure -- skip straight to the fallback rather
than raising, so a Claude outage degrades the narration, not the whole
verdict request.

Cache lookups happen one layer up, in `api.persona.service` -- this module
always makes at least one Claude call (or returns the fallback), never
inspects a cache itself.
"""

from __future__ import annotations

import logging

import anthropic

from api.persona.claude_client import Narrator
from api.persona.grounding import find_ungrounded_tokens
from api.persona.prompt import build_system_prompt, build_user_message

logger = logging.getLogger(__name__)

# The SDK's own `max_retries` (default 2) already covers 429/5xx/connection
# retries transparently -- this is a separate, app-level concern: what to
# do once the SDK gives up (or a non-retryable APIStatusError comes back).
_TRANSPORT_ERRORS = (anthropic.APIStatusError, anthropic.APIConnectionError)


def _grounding_feedback(mismatches: list[str]) -> str:
    quoted = ", ".join(f'"{token}"' for token in mismatches)
    return (
        f"That wasn't fully grounded in the FACT BLOCK -- you said {quoted}, "
        "which don't appear there. Rewrite your answer using only names, "
        "numbers, and records that appear in the FACT BLOCK above."
    )


def narrate(
    *,
    fact_block_json: str,
    user_team: str | None,
    contested: bool,
    known_team_names: list[str],
    narrator: Narrator,
    fallback_text: str,
) -> str:
    """Narrate `fact_block_json` in-character. Never raises: a Claude
    outage or two grounding failures both degrade to `fallback_text`.
    """
    system_prompt = build_system_prompt(user_team)
    user_message = build_user_message(fact_block_json, contested=contested)
    messages: list[dict[str, str]] = [{"role": "user", "content": user_message}]

    try:
        text = narrator.complete(system=system_prompt, messages=messages)
    except _TRANSPORT_ERRORS as exc:
        logger.warning("Claude API call failed, serving fallback narration: %s", exc)
        return fallback_text

    mismatches = find_ungrounded_tokens(text, fact_block_json, known_team_names)
    if not mismatches:
        return text

    messages.append({"role": "assistant", "content": text})
    messages.append({"role": "user", "content": _grounding_feedback(mismatches)})

    try:
        retry_text = narrator.complete(system=system_prompt, messages=messages)
    except _TRANSPORT_ERRORS as exc:
        logger.warning("Claude API call failed on grounding retry, serving fallback: %s", exc)
        return fallback_text

    retry_mismatches = find_ungrounded_tokens(retry_text, fact_block_json, known_team_names)
    if not retry_mismatches:
        return retry_text

    logger.warning(
        "Grounding check failed twice (first mismatches=%s, retry mismatches=%s); "
        "serving templated fallback narration instead of a third Claude call.",
        mismatches,
        retry_mismatches,
    )
    return fallback_text
