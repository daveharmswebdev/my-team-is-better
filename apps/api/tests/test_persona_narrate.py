"""Failing-first tests for `api.persona.narrate` (issue #4's grounding
retry-then-fallback orchestration, Architecture Brief §4.3). Uses a fake
`Narrator` (never the real `anthropic` SDK) so this file needs neither
`ANTHROPIC_API_KEY` nor network access.

Issue #65: `narrate()` returns a `NarrationResult` that says whether it
degraded to the fallback, so its caller can refuse to cache a fallback. Every
path below asserts that flag, not just the text.
"""

from __future__ import annotations

import anthropic
import httpx2

from api.persona.narrate import NarrationResult, narrate

FACT_BLOCK = (
    '{"team_name": "Texas", "year": 2005, "wins": 13, "losses": 0, "rank": 1, '
    '"quality_wins": [{"opponent_name": "USC", "team_score": 41, "opponent_score": 38}]}'
)
KNOWN_TEAMS = ["Texas", "USC", "Alabama"]
FALLBACK_TEXT = "Texas finished 13-0 in 2005, ranked #1 -- the numbers speak for themselves."


class _ScriptedNarrator:
    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.calls: list[list[dict[str, str]]] = []

    def complete(self, *, system: str, messages: list[dict[str, str]]) -> str:
        self.calls.append(messages)
        return self.responses.pop(0)


class _RaisingNarrator:
    def __init__(self, error: Exception) -> None:
        self.error = error
        self.calls: list[list[dict[str, str]]] = []

    def complete(self, *, system: str, messages: list[dict[str, str]]) -> str:
        self.calls.append(messages)
        raise self.error


class _RaisesOnRetryNarrator:
    """Answers the first call with `first`, then raises `error` on the retry."""

    def __init__(self, first: str, error: Exception) -> None:
        self.first = first
        self.error = error
        self.calls: list[list[dict[str, str]]] = []

    def complete(self, *, system: str, messages: list[dict[str, str]]) -> str:
        self.calls.append(messages)
        if len(self.calls) == 1:
            return self.first
        raise self.error


def test_grounded_first_response_is_returned_with_a_single_call() -> None:
    narrator = _ScriptedNarrator(["Texas ran the table at 13-0 in 2005, beating USC 41-38."])

    result = narrate(
        fact_block_json=FACT_BLOCK,
        user_team=None,
        contested=False,
        known_team_names=KNOWN_TEAMS,
        narrator=narrator,
        fallback_text=FALLBACK_TEXT,
    )

    assert result == NarrationResult(
        text="Texas ran the table at 13-0 in 2005, beating USC 41-38.", is_fallback=False
    )
    assert len(narrator.calls) == 1


def test_ungrounded_first_response_retries_once_with_feedback_then_succeeds() -> None:
    narrator = _ScriptedNarrator(
        [
            "Texas would have smoked Alabama too, probably.",  # ungrounded mention
            "Texas ran the table at 13-0 in 2005, beating USC 41-38.",
        ]
    )

    result = narrate(
        fact_block_json=FACT_BLOCK,
        user_team=None,
        contested=False,
        known_team_names=KNOWN_TEAMS,
        narrator=narrator,
        fallback_text=FALLBACK_TEXT,
    )

    assert result == NarrationResult(
        text="Texas ran the table at 13-0 in 2005, beating USC 41-38.", is_fallback=False
    )
    assert len(narrator.calls) == 2
    # The retry's follow-up message must quote the offending token.
    retry_messages = narrator.calls[1]
    feedback = retry_messages[-1]["content"]
    assert "Alabama" in feedback


def test_two_ungrounded_responses_serve_the_fallback_and_never_make_a_third_call() -> None:
    narrator = _ScriptedNarrator(
        [
            "Texas would have smoked Alabama too, probably.",
            "Honestly Alabama would have had a case too, who knows.",
        ]
    )

    result = narrate(
        fact_block_json=FACT_BLOCK,
        user_team=None,
        contested=False,
        known_team_names=KNOWN_TEAMS,
        narrator=narrator,
        fallback_text=FALLBACK_TEXT,
    )

    assert result == NarrationResult(text=FALLBACK_TEXT, is_fallback=True)
    assert len(narrator.calls) == 2


def test_claude_api_connection_error_falls_back_without_crashing() -> None:
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    narrator = _RaisingNarrator(anthropic.APIConnectionError(request=request))

    result = narrate(
        fact_block_json=FACT_BLOCK,
        user_team=None,
        contested=False,
        known_team_names=KNOWN_TEAMS,
        narrator=narrator,
        fallback_text=FALLBACK_TEXT,
    )

    assert result == NarrationResult(text=FALLBACK_TEXT, is_fallback=True)
    assert len(narrator.calls) == 1


def test_claude_api_error_on_the_grounding_retry_falls_back_without_crashing() -> None:
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    narrator = _RaisesOnRetryNarrator(
        "Texas would have smoked Alabama too, probably.",
        anthropic.APIConnectionError(request=request),
    )

    result = narrate(
        fact_block_json=FACT_BLOCK,
        user_team=None,
        contested=False,
        known_team_names=KNOWN_TEAMS,
        narrator=narrator,
        fallback_text=FALLBACK_TEXT,
    )

    assert result == NarrationResult(text=FALLBACK_TEXT, is_fallback=True)
    assert len(narrator.calls) == 2


def test_relational_score_order_mismatch_retries_then_succeeds() -> None:
    # issue #26 regression: `narrate()` doesn't reimplement grounding logic,
    # it just calls `find_ungrounded_tokens` and checks for a non-empty
    # list -- confirm that wiring actually catches a relational (order
    # swapped) mismatch, not just plain token-membership ones.
    swapped_fact_block = (
        '{"team_name": "Vanderbilt", "year": 2025, "wins": 10, "losses": 3, '
        '"rank": 21, "games": [], "quality_wins": ['
        '{"opponent_name": "Texas", "team_score": 31, "opponent_score": 34, '
        '"result": "L"}], "worst_loss": null}'
    )
    narrator = _ScriptedNarrator(
        [
            "Vanderbilt had a great year, beating Texas (34-31) along the way.",
            "Vanderbilt had a great year, falling to Texas (31-34) along the way.",
        ]
    )

    result = narrate(
        fact_block_json=swapped_fact_block,
        user_team=None,
        contested=False,
        known_team_names=["Vanderbilt", "Texas"],
        narrator=narrator,
        fallback_text=FALLBACK_TEXT,
    )

    assert result == NarrationResult(
        text="Vanderbilt had a great year, falling to Texas (31-34) along the way.",
        is_fallback=False,
    )
    assert len(narrator.calls) == 2
    retry_messages = narrator.calls[1]
    feedback = retry_messages[-1]["content"]
    # Finding 3: the feedback must name the correct order explicitly (not
    # just repeat the wrong one), since "34" and "31" are each individually
    # present in the FACT BLOCK -- the old "which don't appear there"
    # wording was literally false and gave the retry nothing concrete to
    # self-correct from.
    assert "should be stated 31-34, not 34-31" in feedback


def test_claude_api_status_error_falls_back_without_crashing() -> None:
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx2.Response(status_code=529, request=request)
    error = anthropic.APIStatusError("overloaded", response=response, body=None)
    narrator = _RaisingNarrator(error)

    result = narrate(
        fact_block_json=FACT_BLOCK,
        user_team=None,
        contested=False,
        known_team_names=KNOWN_TEAMS,
        narrator=narrator,
        fallback_text=FALLBACK_TEXT,
    )

    assert result == NarrationResult(text=FALLBACK_TEXT, is_fallback=True)
    assert len(narrator.calls) == 1
