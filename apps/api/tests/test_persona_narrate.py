"""Failing-first tests for `api.persona.narrate` (issue #291, epic #199 child 2
of 4): production narration goes through the typed-claim tool call.

Every narration served is `claims.check_and_render`'s rendered text for one
forced `submit_narration` call. The budget is one call, at most one retry that
feeds the claim errors back as an `is_error` tool_result, then the templated
fallback; a transport error on either call is the fallback too. The feedback
and the fallback log are capped (founder decision 2 on #291): the first 10
errors in validator order, then "…and N more errors", at most 8,000 characters.

Uses a scripted fake `Narrator` (never the real `anthropic` SDK, no key, no
network) against the real 2005 Texas team-case fact block and the real CFB
catalog from `tests/fixtures/claim_blocks.py`.

Issue #65: `narrate()` returns a `NarrationResult` that says whether it
degraded to the fallback, so its caller can refuse to cache a fallback. Every
path below asserts that flag, not just the text.
"""

from __future__ import annotations

import logging

import anthropic
import httpx2
import pytest
from anthropic.types import MessageParam
from fixtures.claim_blocks import cfb_catalog, cfb_team_case_block
from fixtures.narrator_fake import FakeNarrator, no_tool_reply

from api.persona.claims import TOOL_NAME, check_and_render
from api.persona.claude_client import NarratorReply, ToolCall, tool_reply
from api.persona.narrate import (
    MAX_FEEDBACK_CHARS,
    MAX_FEEDBACK_ERRORS,
    NarrationResult,
    cap_feedback,
    narrate,
)
from api.persona.prompt import build_system_prompt, build_user_message

FALLBACK_TEXT = "Texas finished 13-0 in 2005, ranked #1 -- the numbers speak for themselves."

GOOD: dict[str, object] = {
    "text": "Look at {rec} in {yr}.",
    "claims": [{"id": "rec", "kind": "record", "team": "Texas"}, {"id": "yr", "kind": "year"}],
}
GOOD_RENDERED = "Look at Texas 13-0 in 2005."

RETRY_GOOD: dict[str, object] = {
    "text": "They went through USC {g1} {w1}.",
    "claims": [
        {"id": "g1", "kind": "game_score", "team": "Texas", "opponent": "USC", "result": "W"},
        {"id": "w1", "kind": "when", "team": "Texas", "opponent": "USC", "result": "W"},
    ],
}
RETRY_RENDERED = "They went through USC 41-38 in the postseason."

# A nickname and a typed score: two claim errors.
BAD: dict[str, object] = {"text": "The Longhorns beat USC 41-38.", "claims": []}

# Issue #291's measured flood: 4,000 typed numbers, 4,000 errors.
FLOOD: dict[str, object] = {"text": " ".join(f"{i}." for i in range(4000)), "claims": []}


def _block() -> str:
    return cfb_team_case_block(2005, "Texas")


def _narrate(narrator: FakeNarrator, *, user_team: str | None = None) -> NarrationResult:
    return narrate(
        fact_block_json=_block(),
        user_team=user_team,
        contested=False,
        catalog=cfb_catalog(),
        narrator=narrator,
        fallback_text=FALLBACK_TEXT,
    )


def _connection_error() -> anthropic.APIConnectionError:
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    return anthropic.APIConnectionError(request=request)


def _tool_result(message: MessageParam) -> dict[str, object]:
    """The one tool_result block a retry's user turn holds."""
    assert message["role"] == "user"
    content = message["content"]
    assert not isinstance(content, str), content
    blocks = list(content)
    assert len(blocks) == 1, blocks
    (block,) = blocks
    assert isinstance(block, dict)
    return dict(block)


def _feedback_errors(feedback: str) -> list[str]:
    return [line[len("- ") :] for line in feedback.split("\n") if line.startswith("- ")]


def test_the_fixture_submissions_are_what_these_tests_say() -> None:
    catalog = cfb_catalog()
    assert check_and_render(GOOD, _block(), catalog).text == GOOD_RENDERED
    assert check_and_render(RETRY_GOOD, _block(), catalog).text == RETRY_RENDERED
    assert len(check_and_render(BAD, _block(), catalog).errors) == 2
    assert len(check_and_render(FLOOD, _block(), catalog).errors) == 4000


# ---------------------------------------------------------------------------
# the call budget
# ---------------------------------------------------------------------------


def test_a_valid_first_submission_serves_the_rendered_text_with_one_call() -> None:
    narrator = FakeNarrator([tool_reply(GOOD)])

    result = _narrate(narrator)

    assert result == NarrationResult(text=GOOD_RENDERED, is_fallback=False)
    assert "{" not in result.text, "the raw placeholder text was served"
    assert len(narrator.calls) == 1
    (call,) = narrator.calls
    assert call.system == build_system_prompt(None)
    assert call.messages == [
        {"role": "user", "content": build_user_message(_block(), contested=False)}
    ]


def test_a_rejected_submission_is_retried_once_with_its_errors_as_an_error_tool_result() -> None:
    first = tool_reply(BAD, tool_use_id="toolu_first")
    narrator = FakeNarrator([first, tool_reply(RETRY_GOOD, tool_use_id="toolu_second")])

    result = _narrate(narrator)

    assert result == NarrationResult(text=RETRY_RENDERED, is_fallback=False)
    assert len(narrator.calls) == 2
    retry = narrator.calls[1].messages
    assert len(retry) == 3
    assert retry[0] == narrator.calls[0].messages[0]
    assert retry[1] == {"role": "assistant", "content": list(first.assistant_content)}
    block = _tool_result(retry[2])
    assert block["type"] == "tool_result"
    assert block["tool_use_id"] == "toolu_first"
    assert block["is_error"] is True
    feedback = block["content"]
    assert isinstance(feedback, str)
    assert feedback.startswith("Rejected, nothing was shown to the user.")
    assert _feedback_errors(feedback) == list(check_and_render(BAD, _block(), cfb_catalog()).errors)
    assert narrator.calls[1].system == narrator.calls[0].system


def test_a_second_rejection_serves_the_fallback_and_never_makes_a_third_call() -> None:
    narrator = FakeNarrator([tool_reply(BAD), tool_reply(BAD), tool_reply(GOOD)])

    result = _narrate(narrator)

    assert result == NarrationResult(text=FALLBACK_TEXT, is_fallback=True)
    assert len(narrator.calls) == 2
    assert narrator.pending == 1, "the third scripted reply must never be asked for"


def test_an_over_cap_submission_is_never_served() -> None:
    # Nine claims: one over the cap of 8 (#291 round 2).
    claims = [{"id": f"y{i}", "kind": "year"} for i in range(9)]
    over_cap: dict[str, object] = {
        "text": " ".join(f"{{y{i}}}" for i in range(9)),
        "claims": claims,
    }
    narrator = FakeNarrator([tool_reply(over_cap), tool_reply(over_cap)])

    result = _narrate(narrator)

    assert result == NarrationResult(text=FALLBACK_TEXT, is_fallback=True)
    feedback = _tool_result(narrator.calls[1].messages[-1])["content"]
    assert isinstance(feedback, str) and "9 claims" in feedback


def test_a_reply_with_no_tool_call_is_retried_with_a_text_turn() -> None:
    narrator = FakeNarrator([no_tool_reply(), tool_reply(GOOD)])

    result = _narrate(narrator)

    assert result == NarrationResult(text=GOOD_RENDERED, is_fallback=False)
    assert len(narrator.calls) == 2
    retry = narrator.calls[1].messages
    assert len(retry) == 2
    assert retry[0] == narrator.calls[0].messages[0]
    assert retry[1]["role"] == "user"
    feedback = retry[1]["content"]
    assert isinstance(feedback, str)
    assert feedback.startswith("Rejected, nothing was shown to the user.")
    assert TOOL_NAME in feedback


def test_two_replies_with_no_tool_call_serve_the_fallback() -> None:
    narrator = FakeNarrator([no_tool_reply(), no_tool_reply("Still Texas.")])

    assert _narrate(narrator) == NarrationResult(text=FALLBACK_TEXT, is_fallback=True)
    assert len(narrator.calls) == 2


def test_a_connection_error_on_the_first_call_serves_the_fallback() -> None:
    narrator = FakeNarrator([_connection_error()])

    assert _narrate(narrator) == NarrationResult(text=FALLBACK_TEXT, is_fallback=True)
    assert len(narrator.calls) == 1


def test_a_connection_error_on_the_retry_serves_the_fallback() -> None:
    narrator = FakeNarrator([tool_reply(BAD), _connection_error()])

    assert _narrate(narrator) == NarrationResult(text=FALLBACK_TEXT, is_fallback=True)
    assert len(narrator.calls) == 2


def test_a_status_error_serves_the_fallback() -> None:
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx2.Response(status_code=529, request=request)
    error = anthropic.APIStatusError("overloaded", response=response, body=None)
    narrator = FakeNarrator([error])

    assert _narrate(narrator) == NarrationResult(text=FALLBACK_TEXT, is_fallback=True)
    assert len(narrator.calls) == 1


def test_a_hostile_tool_input_is_a_rejection_not_a_crash() -> None:
    hostile = NarratorReply(
        tool_call=ToolCall(id="toolu_hostile", input=["not", "an", "object"]),
        assistant_content=(),
        stop_reason="tool_use",
    )
    narrator = FakeNarrator([hostile, tool_reply(GOOD)])

    assert _narrate(narrator) == NarrationResult(text=GOOD_RENDERED, is_fallback=False)


# `test_production_narration_never_calls_the_lexical_grounding_check` stood
# here until #292. It monkeypatched `api.persona.grounding.find_ungrounded_tokens`
# to raise and proved production never reached it; with that module deleted the
# property is structural, and there is nothing left to import, let alone patch.
# The rejection path it exercised is covered above, by `check_and_render`.


# ---------------------------------------------------------------------------
# the feedback cap (founder decision 2 on #291)
# ---------------------------------------------------------------------------


def test_the_cap_is_ten_errors_and_eight_thousand_characters() -> None:
    assert (MAX_FEEDBACK_ERRORS, MAX_FEEDBACK_CHARS) == (10, 8000)


def test_a_four_thousand_number_flood_feeds_back_exactly_the_first_ten_errors() -> None:
    errors = check_and_render(FLOOD, _block(), cfb_catalog()).errors
    narrator = FakeNarrator([tool_reply(FLOOD), tool_reply(GOOD)])

    assert _narrate(narrator) == NarrationResult(text=GOOD_RENDERED, is_fallback=False)

    feedback = _tool_result(narrator.calls[1].messages[-1])["content"]
    assert isinstance(feedback, str)
    assert len(feedback) <= MAX_FEEDBACK_CHARS
    assert _feedback_errors(feedback) == list(errors[:10])
    assert feedback.endswith("\n…and 3990 more errors")


def test_feedback_is_cut_at_an_error_boundary() -> None:
    errors = [c * 3000 for c in "abcde"]

    feedback = cap_feedback(errors, header="Rejected:")

    assert len(feedback) <= MAX_FEEDBACK_CHARS
    shown = _feedback_errors(feedback)
    assert shown == errors[: len(shown)]
    assert 1 <= len(shown) < len(errors)
    assert feedback.endswith(f"\n…and {len(errors) - len(shown)} more errors")


def test_a_single_error_longer_than_the_budget_is_truncated_to_fit() -> None:
    alone = cap_feedback(["x" * 9000], header="Rejected:")
    assert len(alone) <= MAX_FEEDBACK_CHARS
    assert alone.startswith("Rejected:\n- xxx")
    assert "more error" not in alone

    with_another = cap_feedback(["x" * 9000, "short"], header="Rejected:")
    assert len(with_another) <= MAX_FEEDBACK_CHARS
    assert with_another.startswith("Rejected:\n- xxx")
    assert with_another.endswith("\n…and 1 more error")


def test_ten_or_fewer_short_errors_are_fed_back_whole() -> None:
    errors = [f"error number {i}" for i in range(10)]

    assert cap_feedback(errors, header="Rejected:") == "Rejected:\n" + "\n".join(
        f"- {error}" for error in errors
    )


def test_the_fallback_warning_log_is_capped_too(caplog: pytest.LogCaptureFixture) -> None:
    errors = check_and_render(FLOOD, _block(), cfb_catalog()).errors
    narrator = FakeNarrator([tool_reply(FLOOD), tool_reply(FLOOD)])

    with caplog.at_level(logging.WARNING, logger="api.persona.narrate"):
        result = _narrate(narrator)

    assert result == NarrationResult(text=FALLBACK_TEXT, is_fallback=True)
    records = [r for r in caplog.records if r.name == "api.persona.narrate"]
    assert len(records) == 1
    message = records[0].getMessage()
    assert len(message) <= MAX_FEEDBACK_CHARS
    assert _feedback_errors(message) == list(errors[:10])
    assert "…and 3990 more errors" in message
