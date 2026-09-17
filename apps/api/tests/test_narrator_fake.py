"""Failing-first tests for issue #212: one shared `Narrator` test double.

Twenty-two near-identical doubles used to sit in twenty-one test files, each
re-deriving the same two behaviours: answer with a scripted reply, and record
the `system` and `messages` the call carried. `tests/fixtures/narrator_fake.py`
is now the only one, and this file pins the behaviours the twenty relied on so
a change to the fake fails here rather than scattering across the suite.

The fake is a test double, not production code:
`api.persona.claude_client.StubNarrator` is the `APP_TEST_MODE=1` production
stand-in and stays what it is.
"""

from __future__ import annotations

import pytest
from anthropic.types import MessageParam
from fixtures.narrator_fake import (
    ACCEPTED_NARRATION,
    FakeNarrator,
    NarratorCall,
    no_tool_reply,
)

from api.persona.claims import TOOL_NAME
from api.persona.claude_client import Narrator, NarratorReply, ToolCall, tool_reply

FIRST: list[MessageParam] = [{"role": "user", "content": "FACT BLOCK\nfirst"}]
SECOND: list[MessageParam] = [
    {"role": "user", "content": "FACT BLOCK\nfirst"},
    {"role": "user", "content": "Rejected"},
]


def test_the_fake_satisfies_the_narrator_protocol() -> None:
    narrator: Narrator = FakeNarrator()
    reply = narrator.submit(system="s", messages=list(FIRST))
    assert isinstance(reply, NarratorReply)


def test_with_no_script_every_call_is_accepted_and_claimless() -> None:
    narrator = FakeNarrator()
    for _ in range(3):
        reply = narrator.submit(system="s", messages=list(FIRST))
        assert reply.tool_call == ToolCall(
            id="toolu_stub", input={"text": ACCEPTED_NARRATION, "claims": []}
        )
    assert len(narrator.calls) == 3


def test_the_default_submission_is_shaped_like_a_real_tool_call() -> None:
    narrator = FakeNarrator()
    reply = narrator.submit(system="s", messages=list(FIRST))
    assert reply.stop_reason == "tool_use"
    assert reply.assistant_content == (
        {
            "type": "tool_use",
            "id": "toolu_stub",
            "name": TOOL_NAME,
            "input": {"text": ACCEPTED_NARRATION, "claims": []},
        },
    )


def test_a_scripted_sequence_is_answered_in_order() -> None:
    narrator = FakeNarrator([{"text": "one {a}", "claims": []}, {"text": "two", "claims": []}])
    first = narrator.submit(system="s", messages=list(FIRST))
    second = narrator.submit(system="s", messages=list(SECOND))
    assert first.tool_call is not None and second.tool_call is not None
    assert first.tool_call.input == {"text": "one {a}", "claims": []}
    assert second.tool_call.input == {"text": "two", "claims": []}


def test_a_scripted_string_is_a_claimless_submission_of_that_text() -> None:
    narrator = FakeNarrator(["Nobody's arguing."])
    reply = narrator.submit(system="s", messages=list(FIRST))
    assert reply.tool_call is not None
    assert reply.tool_call.input == {"text": "Nobody's arguing.", "claims": []}


def test_a_scripted_narrator_reply_is_returned_as_is() -> None:
    scripted = no_tool_reply("Texas, easy.")
    narrator = FakeNarrator([scripted])
    assert narrator.submit(system="s", messages=list(FIRST)) is scripted


def test_no_tool_reply_carries_no_tool_call_and_replays_its_text() -> None:
    reply = no_tool_reply("Texas, easy.")
    assert reply.tool_call is None
    assert reply.assistant_content == ({"type": "text", "text": "Texas, easy."},)
    assert reply.stop_reason == "end_turn"


def test_a_scripted_exception_is_raised_on_that_call() -> None:
    boom = RuntimeError("transport")
    narrator = FakeNarrator([{"text": "fine", "claims": []}, boom])
    narrator.submit(system="s", messages=list(FIRST))
    with pytest.raises(RuntimeError, match="transport"):
        narrator.submit(system="s", messages=list(SECOND))
    assert len(narrator.calls) == 2, "a raising call is still recorded"


def test_a_script_that_runs_out_fails_loudly() -> None:
    narrator = FakeNarrator([{"text": "only one", "claims": []}])
    narrator.submit(system="s", messages=list(FIRST))
    with pytest.raises(AssertionError, match="ran out"):
        narrator.submit(system="s", messages=list(SECOND))


def test_pending_counts_the_scripted_replies_never_used() -> None:
    narrator = FakeNarrator([{"text": "one", "claims": []}, {"text": "two", "claims": []}])
    assert narrator.pending == 2
    narrator.submit(system="s", messages=list(FIRST))
    assert narrator.pending == 1


def test_pending_is_zero_without_a_script() -> None:
    assert FakeNarrator().pending == 0
    assert FakeNarrator(always=no_tool_reply()).pending == 0


def test_always_answers_every_call_with_the_same_reply() -> None:
    narrator = FakeNarrator(always=no_tool_reply())
    for _ in range(3):
        assert narrator.submit(system="s", messages=list(FIRST)).tool_call is None
    assert len(narrator.calls) == 3


def test_always_can_raise_on_every_call() -> None:
    narrator = FakeNarrator(always=RuntimeError("down"))
    with pytest.raises(RuntimeError, match="down"):
        narrator.submit(system="s", messages=list(FIRST))
    with pytest.raises(RuntimeError, match="down"):
        narrator.submit(system="s", messages=list(SECOND))


def test_reply_for_decides_from_the_call_it_was_handed() -> None:
    narrator = FakeNarrator(
        reply_for=lambda call: {"text": f"call {len(call.messages)}", "claims": []}
    )
    first = narrator.submit(system="s", messages=list(FIRST))
    second = narrator.submit(system="s", messages=list(SECOND))
    assert first.tool_call is not None and second.tool_call is not None
    assert first.tool_call.input == {"text": "call 1", "claims": []}
    assert second.tool_call.input == {"text": "call 2", "claims": []}


def test_only_one_reply_source_may_be_given() -> None:
    with pytest.raises(AssertionError, match="exactly one"):
        FakeNarrator([{"text": "x", "claims": []}], always=no_tool_reply())


def test_every_call_records_its_system_and_messages() -> None:
    narrator = FakeNarrator()
    narrator.submit(system="prompt one", messages=list(FIRST))
    narrator.submit(system="prompt two", messages=list(SECOND))

    assert narrator.calls == [
        NarratorCall(system="prompt one", messages=list(FIRST)),
        NarratorCall(system="prompt two", messages=list(SECOND)),
    ]
    assert narrator.systems == ["prompt one", "prompt two"]
    assert narrator.messages == [list(FIRST), list(SECOND)]


def test_the_recorded_messages_are_a_snapshot_not_the_live_list() -> None:
    narrator = FakeNarrator()
    sent = list(FIRST)
    narrator.submit(system="s", messages=sent)
    sent.append({"role": "user", "content": "appended after the call"})

    assert narrator.messages == [list(FIRST)]


def test_a_call_reads_back_the_text_of_its_plain_user_turns() -> None:
    narrator = FakeNarrator()
    narrator.submit(system="s", messages=list(SECOND))

    assert narrator.calls[0].user_texts == ("FACT BLOCK\nfirst", "Rejected")


def test_user_texts_skips_a_turn_of_content_blocks() -> None:
    narrator = FakeNarrator()
    narrator.submit(
        system="s",
        messages=[
            {"role": "user", "content": "FACT BLOCK\nfirst"},
            {"role": "assistant", "content": list(tool_reply({"text": "x"}).assistant_content)},
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_stub",
                        "is_error": True,
                        "content": "Rejected",
                    }
                ],
            },
        ],
    )

    assert narrator.calls[0].user_texts == ("FACT BLOCK\nfirst",)


def test_a_call_reads_back_its_retry_feedback() -> None:
    narrator = FakeNarrator()
    narrator.submit(
        system="s",
        messages=[
            {"role": "user", "content": "FACT BLOCK\nfirst"},
            {"role": "assistant", "content": list(tool_reply({"text": "x"}).assistant_content)},
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_stub",
                        "is_error": True,
                        "content": "Rejected, nothing was shown",
                    }
                ],
            },
        ],
    )

    assert narrator.calls[0].retry_feedback == "Rejected, nothing was shown"


def test_retry_feedback_on_a_plain_text_retry_turn() -> None:
    narrator = FakeNarrator()
    narrator.submit(
        system="s",
        messages=[
            {"role": "user", "content": "FACT BLOCK\nfirst"},
            {"role": "user", "content": "Rejected, no tool call"},
        ],
    )

    assert narrator.calls[0].retry_feedback == "Rejected, no tool call"


def test_retry_feedback_on_a_first_call_is_none() -> None:
    narrator = FakeNarrator()
    narrator.submit(system="s", messages=list(FIRST))

    assert narrator.calls[0].retry_feedback is None
