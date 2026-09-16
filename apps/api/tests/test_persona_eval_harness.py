"""Offline unit tests for the scored persona eval harness (issue #327).

The harness itself (`tests/persona_eval_harness/`) is a dev tool run on
demand with a key; it never runs in pytest and never fails CI on a score.
These tests are its CI half, and none of them makes a Claude call: every
narrator is a scripted fake, every grader client a fake that returns a
hand-built `anthropic.types.Message`, and the environment the safety checks
read is a plain mapping handed to `main`, never the process environment.

What they pin:

- the dataset: spike #200's 11 fact blocks, each byte-equal to the block its
  `/api/verdict` route hands the narrator (with the same contested flag,
  fallback text and system prompt), through the conftest `client` /
  `sport_client` fixtures;
- variants: `baseline` is production's prompt, `name=path` loads a file, and
  the shipped degraded variant is still a bar-stool narrator asked for a
  `submit_narration` call, minus the rules and worked examples;
- the narrator wrapper swaps `system` and nothing else;
- the runner narrates through production `narrate()` (a served text is the
  validator's rendering, a twice-rejected one is the fallback);
- the model grader's request (Opus 5, structured outputs with the fields in
  order, no sampling parameters, XML-tagged inputs) and its parsing (a
  refusal or unparseable output is ungraded, never a score);
- aggregation, spread and the report files, including zero served and all
  ungraded, a worse variant reading as worse, and the narrator-served-only
  voice mean beside the all-narrations one;
- transport errors: a narration whose narrator call raised is the `error`
  outcome, never graded and outside every rate, and a grader transport error
  is ungraded and counted; either one puts a warning in report.md and on
  stderr and makes the exit code 4;
- `--max-calls` (refused up front, and a hard stop mid-run), the safety
  refusals, and `--dry-run`.
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

import anthropic
import httpx2
import pytest
from anthropic.types import Message, MessageParam, Usage
from fastapi.testclient import TestClient
from fixtures.persona_eval import (
    JudgedCall,
    Judgement,
    NarrationRecord,
    RecordedCall,
    RecordingNarrator,
    ServedBy,
    build_record,
    fact_block_from_user_turn,
)
from persona_eval_harness.budget import (
    BudgetExhausted,
    CallBudget,
    worst_case_calls,
)
from persona_eval_harness.cli import EXIT_TRANSPORT_ERRORS, main
from persona_eval_harness.dataset import CASE_SPECS, EvalCase, build_dataset
from persona_eval_harness.grader import (
    FOUNDER_RULE,
    GRADE_FIELDS,
    GRADER_MAX_TOKENS,
    GRADER_MODEL,
    GRADER_PROMPT_VERSION,
    LENGTH_ASK,
    PRD_CONTESTED,
    PRD_MAY,
    PRD_MAY_NOT,
    PRD_PERSONA,
    Grade,
    ModelGrader,
    parse_grade,
    ungraded,
)
from persona_eval_harness.report import build_report, render_markdown, report_to_json
from persona_eval_harness.runner import (
    ErrorRecordingNarrator,
    HarnessRecord,
    Outcome,
    run_eval,
    run_to_directory,
)
from persona_eval_harness.safety import DEFAULT_ENV_FILE, preflight_refusals
from persona_eval_harness.variants import (
    BASELINE_VARIANT_NAME,
    DEGRADED_VARIANT_NAME,
    SystemSwappingNarrator,
    Variant,
    baseline_variant,
    parse_variant,
    parse_variants,
)

from api.config import PROMPT_VERSION
from api.deps import get_narrator
from api.main import app
from api.persona.claims import GROUNDING_VERSION
from api.persona.claude_client import MODEL, NarratorReply, StubNarrator, tool_reply
from api.persona.prompt import build_system_prompt, build_user_message

TESTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TESTS_DIR.parents[2]
NO_ENV_FILE = Path("/nonexistent/persona-eval-harness/.env")
NOT_A_KEY = "test-placeholder-not-a-key"

TEXAS_CHAMPION = "cfb-2005-champion"
USC_TEAM_CASE = "cfb-2005-usc-team-case"
ALABAMA_CHAMPION = "cfb-2017-champion"

# The persona prompt's GOOD example (persona-v11) on the real 2005 Texas block.
GOOD_TEXAS_INPUT: dict[str, object] = {
    "text": (
        "Look at {rec} in {yr}: they ran the table, and they went through USC — USC! — "
        "{g1} {w1} to prove it. That's not luck, that's a machine."
    ),
    "claims": [
        {"id": "rec", "kind": "record", "team": "Texas"},
        {"id": "yr", "kind": "year"},
        {"id": "g1", "kind": "game_score", "team": "Texas", "opponent": "USC", "result": "W"},
        {"id": "w1", "kind": "when", "team": "Texas", "opponent": "USC", "result": "W"},
    ],
}
GOOD_TEXAS_RENDERED = (
    "Look at Texas 13-0 in 2005: they ran the table, and they went through USC — USC! — "
    "41-38 in the postseason to prove it. That's not luck, that's a machine."
)
TYPED_DIGITS_INPUT: dict[str, object] = {"text": "They went 12-1 and nobody cared.", "claims": []}
GOOD_USC_INPUT: dict[str, object] = {
    "text": "USC went {rec}.",
    "claims": [{"id": "rec", "kind": "record", "team": "USC"}],
}


# ---------------------------------------------------------------------------
# fakes
# ---------------------------------------------------------------------------


def _no_tool_reply() -> NarratorReply:
    return NarratorReply(tool_call=None, assistant_content=(), stop_reason="end_turn")


class _CapturingNoToolNarrator:
    """Answers every call without a tool call, so the route serves its
    fallback; records the system prompt each call carried."""

    def __init__(self) -> None:
        self.systems: list[str] = []

    def submit(self, *, system: str, messages: list[MessageParam]) -> NarratorReply:
        self.systems.append(system)
        return _no_tool_reply()


class _ScriptedNarrator:
    """Replies by fact block: the first call of a narration takes the script's
    first reply, a retry (more than one message) its second."""

    def __init__(self, script: dict[str, Sequence[NarratorReply]]) -> None:
        self.script = script
        self.calls: list[tuple[str, list[MessageParam]]] = []

    def submit(self, *, system: str, messages: list[MessageParam]) -> NarratorReply:
        self.calls.append((system, list(messages)))
        first = messages[0]["content"]
        assert isinstance(first, str)
        replies = self.script[fact_block_from_user_turn(first)]
        return replies[0] if len(messages) == 1 else replies[1]


class _CountingNarrator:
    def __init__(self) -> None:
        self.calls = 0

    def submit(self, *, system: str, messages: list[MessageParam]) -> NarratorReply:
        self.calls += 1
        return StubNarrator().submit(system=system, messages=messages)


class _FakeGrader:
    def __init__(self, score: int = 7, contradictions: tuple[str, ...] = ()) -> None:
        self.calls: list[tuple[str, bool, str]] = []
        self.score = score
        self.contradictions = contradictions

    def grade(self, *, fact_block_json: str, contested: bool, narration: str) -> Grade:
        self.calls.append((fact_block_json, contested, narration))
        return _grade(self.score, contradictions=self.contradictions)


def _transport_error(kind: str) -> anthropic.APIError:
    """An error production `narrate()` answers with the fallback, as the SDK
    raises it once its own retries are spent."""
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    if kind == "connection":
        return anthropic.APIConnectionError(request=request)
    response = httpx2.Response(status_code=529, request=request)
    return anthropic.APIStatusError("overloaded", response=response, body=None)


TRANSPORT_ERROR_KINDS = ("connection", "status")
TRANSPORT_ERROR_TYPES = {"connection": "APIConnectionError", "status": "APIStatusError"}


class _OutageNarrator:
    """The stub reply for every call, except that a call whose system prompt
    isn't production's (so any variant but `baseline`) on one of
    `outage_blocks` raises `error`: an outage that hits one variant only."""

    def __init__(self, error: Exception, outage_blocks: Sequence[str]) -> None:
        self.error = error
        self.outage_blocks = set(outage_blocks)
        self.calls = 0
        self.raised = 0

    def submit(self, *, system: str, messages: list[MessageParam]) -> NarratorReply:
        self.calls += 1
        first = messages[0]["content"]
        assert isinstance(first, str)
        if (
            system != build_system_prompt(None)
            and fact_block_from_user_turn(first) in self.outage_blocks
        ):
            self.raised += 1
            raise self.error
        return StubNarrator().submit(system=system, messages=messages)


class _FailingMessages:
    def create(self, **kwargs: Any) -> Message:
        raise anthropic.APIConnectionError(request=httpx2.Request("POST", "https://test"))


class _FailingAnthropic:
    messages = _FailingMessages()


class _FakeMessages:
    def __init__(self, response: Message) -> None:
        self.response = response
        self.kwargs: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Message:
        self.kwargs.append(kwargs)
        return self.response


class _FakeAnthropic:
    def __init__(self, response: Message) -> None:
        self.messages = _FakeMessages(response)


def _message(content: list[dict[str, object]], stop_reason: str = "end_turn") -> Message:
    return Message.model_validate(
        {
            "id": "msg_test",
            "type": "message",
            "role": "assistant",
            "model": GRADER_MODEL,
            "content": content,
            "stop_reason": stop_reason,
            "stop_sequence": None,
            "usage": Usage(input_tokens=10, output_tokens=20).model_dump(),
        }
    )


GOOD_GRADE_JSON: dict[str, object] = {
    "strengths": ["loud and certain"],
    "weaknesses": ["a little generic"],
    "contradictions": ["'sits atop the standings' for a team ranked 5"],
    "reasoning": "Voice lands; one unsupported claim.",
    "score": 6,
}


def _grade(
    score: int | None, *, contradictions: tuple[str, ...] = (), ungraded: str | None = None
) -> Grade:
    return Grade(
        score=score,
        strengths=(),
        weaknesses=(),
        contradictions=contradictions,
        reasoning=None if score is None else "fine",
        ungraded_reason=ungraded if score is None else None,
        stop_reason="end_turn",
        raw_text="",
    )


@pytest.fixture(scope="module")
def dataset() -> tuple[EvalCase, ...]:
    return build_dataset()


@pytest.fixture(scope="module")
def dataset_by_id(dataset: tuple[EvalCase, ...]) -> dict[str, EvalCase]:
    return {case.id: case for case in dataset}


# ---------------------------------------------------------------------------
# the dataset
# ---------------------------------------------------------------------------


def test_the_dataset_is_spike_200s_eleven_cases(dataset: tuple[EvalCase, ...]) -> None:
    assert [case.id for case in dataset] == [spec.id for spec in CASE_SPECS]
    assert len(dataset) == 11
    assert [case.id for case in dataset if case.contested] == [
        "cfb-2003-champion",
        "cfb-2017-champion",
    ]
    assert {case.spec.kind for case in dataset} == {"champion", "team_case", "compare"}
    assert all(case.user_team is None for case in dataset)
    assert [case.spec.method for case in dataset if case.spec.method != "keener"] == ["elo"]
    assert [case.spec.sport for case in dataset if case.spec.sport != "cfb"] == ["nfl"]


@pytest.mark.parametrize("spec", CASE_SPECS, ids=lambda spec: spec.id)
def test_every_dataset_block_is_the_block_its_route_narrates(
    spec: Any, dataset_by_id: dict[str, EvalCase], request: pytest.FixtureRequest
) -> None:
    client = cast(
        TestClient, request.getfixturevalue("sport_client" if spec.sport == "nfl" else "client")
    )
    case = dataset_by_id[spec.id]
    inner = _CapturingNoToolNarrator()
    recorder = RecordingNarrator(inner)
    app.dependency_overrides[get_narrator] = lambda: recorder

    response = client.post(spec.route, json=spec.request_body)
    assert response.status_code == 200, response.text
    body = response.json()

    calls = recorder.recorded_calls()
    assert len(calls) == 2, "a reply with no tool call is rejected twice, then the fallback"
    assert all(call.fact_block_json == case.fact_block_json for call in calls)
    assert recorder.messages[0][0]["content"] == build_user_message(
        case.fact_block_json, contested=case.contested
    )
    assert body["narration"]["contested"] is case.contested
    assert body["narration"]["text"] == case.fallback_text
    assert inner.systems == [build_system_prompt(case.user_team)] * 2


# ---------------------------------------------------------------------------
# variants
# ---------------------------------------------------------------------------


def test_baseline_is_the_production_prompt() -> None:
    variant = baseline_variant()
    assert variant.name == "baseline"
    for user_team in (None, "Texas"):
        assert variant.build_system_prompt(user_team) == build_system_prompt(user_team)
    assert parse_variant("baseline").build_system_prompt(None) == build_system_prompt(None)


def test_a_name_equals_path_variant_loads(tmp_path: Path) -> None:
    path = tmp_path / "candidate.py"
    path.write_text(
        "def build_system_prompt(user_team: str | None) -> str:\n"
        "    return f'CANDIDATE for {user_team}'\n"
    )
    variant = parse_variant(f"candidate={path}")
    assert variant.name == "candidate"
    assert variant.source == str(path)
    assert variant.build_system_prompt(None) == "CANDIDATE for None"
    assert variant.build_system_prompt("LSU") == "CANDIDATE for LSU"


def test_bad_variant_arguments_are_refused(tmp_path: Path) -> None:
    no_function = tmp_path / "empty.py"
    no_function.write_text("X = 1\n")
    for argument in (
        "nonsense",
        f"={no_function}",
        "missing=/nonexistent/variant.py",
        f"empty={no_function}",
    ):
        with pytest.raises(ValueError):
            parse_variant(argument)
    with pytest.raises(ValueError):
        parse_variants(["baseline", "baseline"])
    with pytest.raises(ValueError):
        parse_variants([])


@pytest.mark.parametrize("reserved", [BASELINE_VARIANT_NAME, DEGRADED_VARIANT_NAME])
def test_a_reserved_name_in_name_equals_path_form_is_refused(reserved: str, tmp_path: Path) -> None:
    path = tmp_path / "x.py"
    path.write_text("def build_system_prompt(user_team: str | None) -> str:\n    return 'X'\n")
    for argument in (f"{reserved}={path}", f" {reserved} ={path}"):
        with pytest.raises(ValueError, match="reserved"):
            parse_variant(argument)
    err = io.StringIO()
    code = main(
        ["--dry-run", "--variant", f"{reserved}={path}"],
        environ={},
        env_file=NO_ENV_FILE,
        out=io.StringIO(),
        err=err,
    )
    assert code == 2
    assert "reserved" in err.getvalue()


def test_the_degraded_variant_is_a_narrator_without_rules_or_examples() -> None:
    degraded = parse_variant(DEGRADED_VARIANT_NAME)
    assert degraded.name == "degraded"
    for user_team in (None, "Texas"):
        prompt = degraded.build_system_prompt(user_team)
        baseline = build_system_prompt(user_team)
        assert prompt != baseline
        assert len(prompt) < len(baseline) / 2
        assert "submit_narration" in prompt
        assert prompt.startswith("You are the loudest guy at the end of the bar.")
        assert "Two or three sentences." in prompt
        for gone in (
            "Rules, non-negotiable",
            "1. You answer with one submit_narration call",
            "2. Never contradict",
            "Example of a GOOD submission",
            "Example of a REJECTED",
            "{rec}",
        ):
            assert gone not in prompt, gone
    assert "Texas" in degraded.build_system_prompt("Texas")


def test_the_system_swapping_narrator_changes_only_system() -> None:
    reply = tool_reply({"text": "Solid case, no notes.", "claims": []})

    class _Inner:
        def __init__(self) -> None:
            self.seen: list[tuple[str, list[MessageParam]]] = []

        def submit(self, *, system: str, messages: list[MessageParam]) -> NarratorReply:
            self.seen.append((system, messages))
            return reply

    inner = _Inner()
    narrator = SystemSwappingNarrator(inner, system="VARIANT PROMPT")
    messages: list[MessageParam] = [
        {"role": "user", "content": "FACT BLOCK (JSON):\n{}\n\ncontested: false"},
        {"role": "assistant", "content": [{"type": "text", "text": "hi"}]},
    ]
    assert narrator.submit(system="PRODUCTION PROMPT", messages=messages) is reply
    ((system, sent),) = inner.seen
    assert system == "VARIANT PROMPT"
    assert sent is messages


# ---------------------------------------------------------------------------
# the runner
# ---------------------------------------------------------------------------


def test_the_runner_narrates_through_production_narrate(
    dataset_by_id: dict[str, EvalCase],
) -> None:
    texas = dataset_by_id[TEXAS_CHAMPION]
    usc = dataset_by_id[USC_TEAM_CASE]
    alabama = dataset_by_id[ALABAMA_CHAMPION]
    narrator = _ScriptedNarrator(
        {
            texas.fact_block_json: [tool_reply(GOOD_TEXAS_INPUT)],
            usc.fact_block_json: [tool_reply(TYPED_DIGITS_INPUT), tool_reply(GOOD_USC_INPUT)],
            alabama.fact_block_json: [tool_reply(TYPED_DIGITS_INPUT)] * 2,
        }
    )
    grader = _FakeGrader(score=8)
    budget = CallBudget(max_calls=100)
    variant = Variant(name="cand", source="test", build_system_prompt=lambda team: f"CAND {team}")

    result = run_eval(
        cases=[texas, usc, alabama],
        variants=[variant],
        samples=1,
        narrator=narrator,
        grader=grader,
        budget=budget,
    )

    assert result.complete
    by_case = {record.case_id: record for record in result.records}
    assert by_case[TEXAS_CHAMPION].served_by == "first"
    assert by_case[TEXAS_CHAMPION].served_text == GOOD_TEXAS_RENDERED
    assert by_case[TEXAS_CHAMPION].claims == 4
    assert by_case[USC_TEAM_CASE].served_by == "retry"
    assert by_case[USC_TEAM_CASE].served_text == "USC went 12-1."
    assert by_case[USC_TEAM_CASE].claims == 1
    assert by_case[ALABAMA_CHAMPION].served_by == "fallback"
    assert by_case[ALABAMA_CHAMPION].served_text == alabama.fallback_text
    assert by_case[ALABAMA_CHAMPION].claims is None
    assert [record.narration.claude_calls for record in result.records] == [1, 2, 2]
    # production's retry: the replayed tool call and an is_error tool_result
    retry_messages = narrator.calls[2][1]
    assert len(retry_messages) == 3
    assert all(system == "CAND None" for system, _ in narrator.calls)
    # every narration is graded, the fallback included, on what the user saw
    assert [narration for _, _, narration in grader.calls] == [
        GOOD_TEXAS_RENDERED,
        "USC went 12-1.",
        alabama.fallback_text,
    ]
    assert grader.calls[2][1] is alabama.contested
    assert result.narrator_calls == 5
    assert result.grader_calls == 3


def test_the_runner_records_code_grader_properties(dataset_by_id: dict[str, EvalCase]) -> None:
    texas = dataset_by_id[TEXAS_CHAMPION]
    long_text = " ".join(["Texas ran them off the field and it was loud."] * 5)
    narrator = _ScriptedNarrator(
        {texas.fact_block_json: [tool_reply({"text": long_text, "claims": []})]}
    )
    result = run_eval(
        cases=[texas],
        variants=[baseline_variant()],
        samples=1,
        narrator=narrator,
        grader=_FakeGrader(),
        budget=CallBudget(max_calls=10),
    )
    (record,) = result.records
    assert record.served_by == "first"
    assert record.narration.over_prompt_length
    assert any(v.startswith("length:") for v in record.property_violations)
    assert record.banned == ()


# ---------------------------------------------------------------------------
# the model grader
# ---------------------------------------------------------------------------


def test_the_grader_request(dataset_by_id: dict[str, EvalCase]) -> None:
    case = dataset_by_id["cfb-2003-champion"]
    fake = _FakeAnthropic(_message([{"type": "text", "text": json.dumps(GOOD_GRADE_JSON)}]))
    grader = ModelGrader(cast(anthropic.Anthropic, fake))

    grade = grader.grade(
        fact_block_json=case.fact_block_json, contested=True, narration="LSU. Loud."
    )

    assert grade.score == 6
    (kwargs,) = fake.messages.kwargs
    assert GRADER_MODEL == "claude-opus-5"
    assert kwargs["model"] == "claude-opus-5"
    assert kwargs["max_tokens"] == GRADER_MAX_TOKENS >= 16000
    assert not {"temperature", "top_p", "top_k", "thinking", "tools", "tool_choice"} & set(kwargs)
    output_format = kwargs["output_config"]["format"]
    assert output_format["type"] == "json_schema"
    schema = output_format["schema"]
    assert GRADE_FIELDS == ("strengths", "weaknesses", "contradictions", "reasoning", "score")
    assert list(schema["properties"]) == list(GRADE_FIELDS)
    assert schema["required"] == list(GRADE_FIELDS)
    assert schema["additionalProperties"] is False
    for field in ("strengths", "weaknesses", "contradictions"):
        assert schema["properties"][field]["type"] == "array"
        assert schema["properties"][field]["items"] == {"type": "string"}
    assert schema["properties"]["reasoning"]["type"] == "string"
    assert schema["properties"]["score"]["type"] == "integer"

    (user_turn,) = kwargs["messages"]
    assert user_turn["role"] == "user"
    content = user_turn["content"]
    assert f"<fact_block>\n{case.fact_block_json}\n</fact_block>" in content
    assert "<narration>\nLSU. Loud.\n</narration>" in content
    assert "<contested>true</contested>" in content
    system = kwargs["system"]
    for rubric in (PRD_PERSONA, PRD_MAY, PRD_MAY_NOT, PRD_CONTESTED, FOUNDER_RULE, LENGTH_ASK):
        assert rubric in system
    assert "The numbers are the numbers. This is math." in system
    assert "Two or three sentences" in system
    assert case.fact_block_json not in system


def test_the_grader_rubric_is_verbatim_from_the_prd() -> None:
    prd = (REPO_ROOT / "docs" / "PRD.md").read_text()
    for excerpt in (PRD_PERSONA, PRD_MAY, PRD_MAY_NOT, PRD_CONTESTED):
        assert excerpt in prd
    # §4's third bullet, as the brief quotes it, with the PRD's line wrap
    assert " ".join(PRD_CONTESTED.split()) == (
        "- When the underlying case is one of those contested years, the UI/persona discloses "
        "that it's contested rather than presenting it as clean-cut."
    )
    assert GRADER_PROMPT_VERSION == "grader-v2"
    assert "**may**" in PRD_MAY
    assert "**may not**" in PRD_MAY_NOT
    assert PRD_PERSONA.startswith("Think: the regular at the end of the bar")


def test_a_grader_transport_error_is_ungraded() -> None:
    grader = ModelGrader(cast(anthropic.Anthropic, _FailingAnthropic()))
    grade = grader.grade(fact_block_json="{}", contested=False, narration="Texas.")
    assert not grade.graded
    assert grade.ungraded_reason is not None and "APIConnectionError" in grade.ungraded_reason
    assert grade.transport_error is not None and "APIConnectionError" in grade.transport_error


def test_a_good_grade_parses() -> None:
    thinking: dict[str, object] = {"type": "thinking", "thinking": "hmm", "signature": "sig"}
    text: dict[str, object] = {"type": "text", "text": json.dumps(GOOD_GRADE_JSON)}
    grade = parse_grade(_message([thinking, text]))
    assert grade.graded
    assert grade.score == 6
    assert grade.strengths == ("loud and certain",)
    assert grade.weaknesses == ("a little generic",)
    assert grade.contradictions == ("'sits atop the standings' for a team ranked 5",)
    assert grade.reasoning == "Voice lands; one unsupported claim."
    assert grade.ungraded_reason is None


def test_a_refusal_is_ungraded_never_a_score() -> None:
    parseable: dict[str, object] = {"type": "text", "text": json.dumps(GOOD_GRADE_JSON)}
    contents: list[list[dict[str, object]]] = [[parseable], []]
    for content in contents:
        grade = parse_grade(_message(content, stop_reason="refusal"))
        assert not grade.graded
        assert grade.score is None
        assert grade.ungraded_reason is not None and "refusal" in grade.ungraded_reason
        assert grade.transport_error is None


@pytest.mark.parametrize(
    "text",
    [
        "not json at all",
        json.dumps({**GOOD_GRADE_JSON, "score": 11}),
        json.dumps({**GOOD_GRADE_JSON, "score": 0}),
        json.dumps({**GOOD_GRADE_JSON, "score": True}),
        json.dumps({**GOOD_GRADE_JSON, "score": 6.5}),
        json.dumps({key: value for key, value in GOOD_GRADE_JSON.items() if key != "score"}),
        json.dumps({**GOOD_GRADE_JSON, "strengths": "one string"}),
        json.dumps([GOOD_GRADE_JSON]),
    ],
)
def test_unparseable_grader_output_is_ungraded(text: str) -> None:
    grade = parse_grade(_message([{"type": "text", "text": text}]))
    assert not grade.graded
    assert grade.score is None
    assert grade.ungraded_reason
    assert grade.raw_text == text
    assert grade.transport_error is None


# ---------------------------------------------------------------------------
# aggregation, spread and the report
# ---------------------------------------------------------------------------

_BLOCK = "{}"


def _narration(served_by: ServedBy, *, text: str = "Texas rolled.") -> NarrationRecord:
    if served_by == "fallback":
        judgement = Judgement(
            served_text="FALLBACK",
            attempts=(),
            served_by="fallback",
            served_attempt=None,
            violations=("not-fallback: fallback",),
        )
        return build_record("case", judgement)
    call = RecordedCall(tool_input={"text": text, "claims": []}, fact_block_json=_BLOCK)
    served = JudgedCall(call=call, errors=(), text=text)
    rejected = JudgedCall(call=call, errors=("typed number",), text=None)
    attempts = (served,) if served_by == "first" else (rejected, served)
    judgement = Judgement(
        served_text=text,
        attempts=attempts,
        served_by=served_by,
        served_attempt=served,
        violations=(),
    )
    return build_record("case", judgement)


def _hrecord(
    *,
    variant: str,
    sample: int,
    served_by: Outcome,
    score: int | None,
    case_id: str = "case-a",
    claims: int | None = 3,
    contradictions: tuple[str, ...] = (),
    text: str = "Texas rolled.",
    grader_error: bool = False,
) -> HarnessRecord:
    """A hand-built record. `error` is a narration whose narrator call raised:
    production served the fallback, and nothing graded it."""
    errored = served_by == "error"
    narration = _narration("fallback" if served_by == "error" else served_by, text=text)
    grade: Grade | None
    if errored:
        grade = None
    elif grader_error:
        grade = ungraded(
            "grader call failed: APIConnectionError: Connection error.",
            transport_error="APIConnectionError: Connection error.",
        )
    else:
        grade = _grade(score, contradictions=contradictions, ungraded="refusal")
    return HarnessRecord(
        variant=variant,
        case_id=case_id,
        sample=sample,
        narration=narration,
        claims=None if served_by in ("fallback", "error") else claims,
        property_violations=(),
        banned=(),
        grade=grade,
        narrator_error="APIConnectionError: Connection error." if errored else None,
    )


def _report_json(
    records: Sequence[HarnessRecord],
    variants: Sequence[str],
    *,
    samples: int,
    complete: bool = True,
    stop_note: str | None = None,
) -> dict[str, Any]:
    report = build_report(
        records=records,
        variants=[Variant(name=name, source="test", build_system_prompt=str) for name in variants],
        case_ids=sorted({record.case_id for record in records}),
        samples=samples,
        complete=complete,
        stop_note=stop_note,
        narrator_calls=10,
        grader_calls=5,
        max_calls=40,
        worst_case_estimate=36,
    )
    as_json = report_to_json(report)
    return cast(dict[str, Any], json.loads(json.dumps(as_json)))


def test_report_json_is_keyed_by_versions_models_and_n() -> None:
    records = [_hrecord(variant="baseline", sample=0, served_by="first", score=7)]
    report = _report_json(records, ["baseline"], samples=1)
    assert report["prompt_version"] == PROMPT_VERSION
    assert report["grounding_version"] == GROUNDING_VERSION
    assert report["narrator_model"] == MODEL
    assert report["grader_model"] == GRADER_MODEL
    assert report["grader_prompt_version"] == "grader-v2"
    assert report["errors"] == {"narrator": 0, "grader": 0}
    assert report["samples"] == 1
    assert report["complete"] is True
    assert report["calls"] == {
        "narrator": 10,
        "grader": 5,
        "total": 15,
        "max_calls": 40,
        "worst_case_estimate": 36,
    }
    (variant,) = report["variants"]
    assert variant["name"] == "baseline"
    assert set(variant["metrics"]) >= {
        "first_try_rate",
        "retry_rate",
        "fallback_rate",
        "claims_per_narration",
        "timing_venue_rate",
        "ambiguous_when_rate",
        "over_three_sentences_rate",
        "lowercase_rejection_rate",
        "property_violation_rate",
        "mean_voice_score",
        "mean_voice_score_served",
        "contradiction_rate",
        "ungraded",
    }
    assert variant["metrics"]["mean_voice_score"] == {"value": 7.0, "min": 7.0, "max": 7.0}
    assert variant["narrator_errors"] == 0 and variant["grader_errors"] == 0


def test_aggregation_and_spread_across_sample_rounds() -> None:
    records = [
        _hrecord(variant="v", sample=0, served_by="first", score=8, claims=4),
        _hrecord(
            variant="v", sample=0, served_by="retry", score=6, claims=2, contradictions=("x",)
        ),
        _hrecord(variant="v", sample=1, served_by="fallback", score=2),
        _hrecord(variant="v", sample=1, served_by="first", score=None),
    ]
    (variant,) = _report_json(records, ["v"], samples=2)["variants"]
    metrics = variant["metrics"]
    assert variant["narrations"] == 4
    assert variant["narrator_served"] == 3
    assert variant["graded"] == 3
    assert variant["ungraded"] == 1
    assert metrics["first_try_rate"] == {"value": 0.5, "min": 0.5, "max": 0.5}
    assert metrics["retry_rate"] == {"value": 0.25, "min": 0.0, "max": 0.5}
    assert metrics["fallback_rate"] == {"value": 0.25, "min": 0.0, "max": 0.5}
    assert metrics["claims_per_narration"] == {"value": 3.0, "min": 3.0, "max": 3.0}
    assert metrics["mean_voice_score"] == {"value": 16 / 3, "min": 2.0, "max": 7.0}
    assert metrics["contradiction_rate"] == {"value": 1 / 3, "min": 0.0, "max": 0.5}
    assert metrics["ungraded"] == {"value": 1, "min": 0, "max": 1}
    assert metrics["lowercase_rejection_rate"]["value"] == 0.0


def test_zero_served_and_all_ungraded_report_none_not_zero() -> None:
    records = [
        _hrecord(variant="v", sample=s, served_by="fallback", score=None, case_id=c)
        for s in (0, 1)
        for c in ("case-a", "case-b")
    ]
    report = _report_json(records, ["v"], samples=2)
    (variant,) = report["variants"]
    metrics = variant["metrics"]
    assert variant["narrator_served"] == 0
    assert variant["graded"] == 0
    assert metrics["fallback_rate"] == {"value": 1.0, "min": 1.0, "max": 1.0}
    for name in (
        "claims_per_narration",
        "timing_venue_rate",
        "ambiguous_when_rate",
        "over_three_sentences_rate",
        "property_violation_rate",
        "mean_voice_score",
        "contradiction_rate",
    ):
        assert metrics[name] == {"value": None, "min": None, "max": None}, name
    assert metrics["ungraded"] == {"value": 4, "min": 2, "max": 2}
    markdown = render_markdown(_report_object(records, ["v"], samples=2))
    assert "n/a" in markdown


def _report_object(
    records: Sequence[HarnessRecord], variants: Sequence[str], *, samples: int
) -> Any:
    return build_report(
        records=records,
        variants=[Variant(name=name, source="test", build_system_prompt=str) for name in variants],
        case_ids=sorted({record.case_id for record in records}),
        samples=samples,
        complete=True,
        stop_note=None,
        narrator_calls=0,
        grader_calls=0,
        max_calls=0,
        worst_case_estimate=0,
    )


def test_an_empty_variant_does_not_crash_the_report() -> None:
    records = [_hrecord(variant="baseline", sample=0, served_by="first", score=7)]
    report = _report_json(records, ["baseline", "degraded"], samples=1)
    degraded = report["variants"][1]
    assert degraded["narrations"] == 0
    assert degraded["metrics"]["first_try_rate"] == {"value": None, "min": None, "max": None}


def _worse_variant_records() -> list[HarnessRecord]:
    records: list[HarnessRecord] = []
    for sample in (0, 1):
        for case_id in ("case-a", "case-b"):
            records.append(
                _hrecord(
                    variant="baseline", sample=sample, served_by="first", score=8, case_id=case_id
                )
            )
            records.append(
                _hrecord(
                    variant="degraded",
                    sample=sample,
                    served_by="fallback" if case_id == "case-a" or sample == 1 else "retry",
                    score=3,
                    case_id=case_id,
                    contradictions=("made up a bowl",),
                )
            )
    return records


def test_a_worse_variant_reads_as_worse_in_report_json_and_markdown() -> None:
    records = _worse_variant_records()
    report = _report_json(records, ["baseline", "degraded"], samples=2)
    baseline, degraded = report["variants"]
    assert baseline["name"] == "baseline" and degraded["name"] == "degraded"
    assert degraded["metrics"]["fallback_rate"]["value"] == 0.75
    assert baseline["metrics"]["fallback_rate"]["value"] == 0.0
    assert degraded["metrics"]["mean_voice_score"]["value"] == 3.0
    assert baseline["metrics"]["mean_voice_score"]["value"] == 8.0
    assert degraded["metrics"]["contradiction_rate"]["value"] == 1.0
    assert (
        degraded["metrics"]["first_try_rate"]["value"]
        < baseline["metrics"]["first_try_rate"]["value"]
    )

    markdown = render_markdown(_report_object(records, ["baseline", "degraded"], samples=2))
    lines = markdown.splitlines()
    header = next(line for line in lines if line.startswith("| metric |"))
    assert header == "| metric | baseline | degraded |"
    assert "| fallback rate | 0% [0%–0%] | 75% [50%–100%] |" in lines
    assert "| mean voice score (1-10) | 8.00 [8.00–8.00] | 3.00 [3.00–3.00] |" in lines
    assert "| first-try valid rate | 100% [100%–100%] | 0% [0%–0%] |" in lines
    assert any(line.startswith("| mean voice score (1-10) | separated: lower") for line in lines)
    assert "samples per case: 2" in markdown
    assert "## Per case" in markdown
    assert any(line.startswith("| case-a |") for line in lines)


def test_a_difference_inside_the_spread_is_marked_as_such() -> None:
    records = [
        _hrecord(variant="baseline", sample=0, served_by="first", score=8),
        _hrecord(variant="baseline", sample=1, served_by="first", score=5),
        _hrecord(variant="candidate", sample=0, served_by="first", score=7),
        _hrecord(variant="candidate", sample=1, served_by="first", score=6),
    ]
    markdown = render_markdown(_report_object(records, ["baseline", "candidate"], samples=2))
    assert "| mean voice score (1-10) | within run-to-run spread |" in markdown.splitlines()


def test_the_served_only_voice_mean_leaves_graded_fallbacks_out() -> None:
    records = [
        _hrecord(variant="v", sample=0, served_by="first", score=8, case_id="case-a"),
        _hrecord(variant="v", sample=0, served_by="fallback", score=2, case_id="case-b"),
        _hrecord(variant="v", sample=1, served_by="retry", score=6, case_id="case-a"),
        _hrecord(variant="v", sample=1, served_by="fallback", score=4, case_id="case-b"),
        _hrecord(variant="v", sample=1, served_by="first", score=None, case_id="case-c"),
    ]
    (variant,) = _report_json(records, ["v"], samples=2)["variants"]
    metrics = variant["metrics"]
    assert metrics["mean_voice_score"] == {"value": 5.0, "min": 5.0, "max": 5.0}
    assert metrics["mean_voice_score_served"] == {"value": 7.0, "min": 6.0, "max": 8.0}
    per_case = {case["case"]: case for case in variant["per_case"]}
    assert per_case["case-a"]["mean_voice_score_served"] == 7.0
    assert per_case["case-b"]["mean_voice_score"] == 3.0
    assert per_case["case-b"]["mean_voice_score_served"] is None
    lines = render_markdown(_report_object(records, ["v"], samples=2)).splitlines()
    assert "| mean voice score, narrator-served only (1-10) | 7.00 [6.00–8.00] |" in lines


def test_the_spread_check_reads_the_served_only_voice_mean_apart_from_fallbacks() -> None:
    """Graded fallbacks pull baseline's all-narrations mean down to the
    candidate's, so only the served-only mean shows the voice gap."""
    baseline_rows: tuple[tuple[Outcome, int, str], ...] = (
        ("first", 8, "case-a"),
        ("fallback", 2, "case-b"),
    )
    records = [
        _hrecord(variant="baseline", sample=s, served_by=served_by, score=score, case_id=case)
        for s in (0, 1)
        for served_by, score, case in baseline_rows
    ] + [
        _hrecord(variant="candidate", sample=s, served_by="first", score=5, case_id=case)
        for s in (0, 1)
        for case in ("case-a", "case-b")
    ]
    report = _report_object(records, ["baseline", "candidate"], samples=2)
    lines = render_markdown(report).splitlines()
    assert "| mean voice score (1-10) | within run-to-run spread |" in lines
    assert (
        "| mean voice score, narrator-served only (1-10) | separated: lower (5.00 vs 8.00) |"
        in lines
    )


# ---------------------------------------------------------------------------
# transport errors
# ---------------------------------------------------------------------------


def test_the_error_recorder_records_and_re_raises() -> None:
    error = _transport_error("connection")
    recorder = ErrorRecordingNarrator(_OutageNarrator(error, outage_blocks=["{}"]))
    messages: list[MessageParam] = [
        {"role": "user", "content": build_user_message("{}", contested=False)}
    ]
    with pytest.raises(anthropic.APIConnectionError):
        recorder.submit(system="NOT PRODUCTION", messages=messages)
    assert recorder.errors == [error]
    reply = recorder.submit(system=build_system_prompt(None), messages=messages)
    assert reply.tool_call is not None
    assert recorder.errors == [error]


@pytest.mark.parametrize("kind", TRANSPORT_ERROR_KINDS)
def test_a_narrator_transport_error_is_an_error_outcome_not_a_fallback(
    kind: str, dataset_by_id: dict[str, EvalCase]
) -> None:
    """The reviewer's scenario: an outage on one variant only. Without the
    error outcome it reads as that variant's fallbacks, 'separated'."""
    texas = dataset_by_id[TEXAS_CHAMPION]
    usc = dataset_by_id[USC_TEAM_CASE]
    narrator = _OutageNarrator(_transport_error(kind), outage_blocks=[usc.fact_block_json])
    grader = _FakeGrader(score=7)
    budget = CallBudget(max_calls=100)
    degraded = Variant(name="degraded", source="test", build_system_prompt=lambda team: "DEGRADED")

    result = run_eval(
        cases=[texas, usc],
        variants=[baseline_variant(), degraded],
        samples=2,
        narrator=narrator,
        grader=grader,
        budget=budget,
    )

    assert result.complete
    errored = [record for record in result.records if record.served_by == "error"]
    assert [(r.variant, r.case_id) for r in errored] == [("degraded", USC_TEAM_CASE)] * 2
    for record in errored:
        assert record.grade is None
        assert record.narrator_error is not None
        assert TRANSPORT_ERROR_TYPES[kind] in record.narrator_error
        # production served its fallback, but the harness doesn't call it one
        assert record.served_text == usc.fallback_text
    assert all(r.served_by == "first" for r in result.records if r.served_by != "error")
    # only the six narrations that didn't error were graded
    assert len(grader.calls) == 6 == result.grader_calls
    assert narrator.raised == 2

    report = build_report(
        records=result.records,
        variants=[baseline_variant(), degraded],
        case_ids=[texas.id, usc.id],
        samples=2,
        complete=result.complete,
        stop_note=None,
        narrator_calls=result.narrator_calls,
        grader_calls=result.grader_calls,
        max_calls=100,
        worst_case_estimate=24,
    )
    as_json = cast(dict[str, Any], json.loads(json.dumps(report_to_json(report))))
    assert as_json["errors"] == {"narrator": 2, "grader": 0}
    baseline_json, degraded_json = as_json["variants"]
    assert baseline_json["narrator_errors"] == 0
    assert degraded_json["narrator_errors"] == 2
    assert degraded_json["narrations"] == 4
    assert degraded_json["narrator_served"] == 2
    assert degraded_json["graded"] == 2 and degraded_json["ungraded"] == 0
    metrics = degraded_json["metrics"]
    for key in ("first_try_rate",):
        assert metrics[key] == {"value": 1.0, "min": 1.0, "max": 1.0}, key
    for key in ("fallback_rate", "retry_rate", "untraceable_rate", "ungraded"):
        assert metrics[key]["value"] == 0, key
    assert metrics["mean_voice_score"] == {"value": 7.0, "min": 7.0, "max": 7.0}
    assert metrics["mean_voice_score_served"] == {"value": 7.0, "min": 7.0, "max": 7.0}
    per_case = {case["case"]: case for case in degraded_json["per_case"]}
    assert per_case[USC_TEAM_CASE]["narrator_errors"] == 2
    assert per_case[USC_TEAM_CASE]["fallback"] == 0
    assert per_case[USC_TEAM_CASE]["mean_voice_score"] is None
    assert per_case[TEXAS_CHAMPION]["narrator_errors"] == 0

    markdown = render_markdown(report)
    assert "separated" not in markdown
    assert "TRANSPORT ERRORS" in markdown
    warning = next(line for line in markdown.splitlines() if "TRANSPORT ERRORS" in line)
    assert "2 narration" in warning
    assert "| narrator errors (excluded from every rate) | 0 | 2 |" in markdown.splitlines()


@pytest.mark.parametrize("kind", TRANSPORT_ERROR_KINDS)
def test_a_narrator_transport_error_warns_and_exits_non_zero(
    kind: str, tmp_path: Path, dataset_by_id: dict[str, EvalCase]
) -> None:
    usc = dataset_by_id[USC_TEAM_CASE]
    narrator = _OutageNarrator(_transport_error(kind), outage_blocks=[usc.fact_block_json])
    grader = _FakeGrader()
    out_dir = tmp_path / "out"
    err = io.StringIO()
    code = main(
        [
            *("--variant", "baseline", "--variant", "degraded"),
            *("--case", TEXAS_CHAMPION, "--case", USC_TEAM_CASE),
            *("--samples", "2", "--max-calls", "24", "--out", str(out_dir)),
        ],
        environ={"ANTHROPIC_API_KEY": NOT_A_KEY},
        env_file=NO_ENV_FILE,
        narrator=narrator,
        grader=grader,
        out=io.StringIO(),
        err=err,
    )
    assert EXIT_TRANSPORT_ERRORS == 4
    assert code == EXIT_TRANSPORT_ERRORS
    assert len(grader.calls) == 6
    warnings = [line for line in err.getvalue().splitlines() if "WARNING" in line]
    assert len(warnings) == 1 and "2 narration" in warnings[0]
    report = json.loads((out_dir / "report.json").read_text())
    assert report["complete"] is True
    assert report["errors"] == {"narrator": 2, "grader": 0}
    assert report["variants"][1]["narrator_errors"] == 2
    markdown = (out_dir / "report.md").read_text()
    assert "TRANSPORT ERRORS" in markdown
    assert "separated" not in markdown
    lines = [json.loads(line) for line in (out_dir / "records.jsonl").read_text().splitlines()]
    errored = [line for line in lines if line["served_by"] == "error"]
    assert len(errored) == 2
    for line in errored:
        assert line["variant"] == "degraded" and line["case"] == USC_TEAM_CASE
        assert line["grade"] is None
        assert TRANSPORT_ERROR_TYPES[kind] in line["narrator_error"]
    assert all(line["narrator_error"] is None for line in lines if line["served_by"] != "error")


def test_a_grader_transport_error_is_counted_warned_and_exits_non_zero(tmp_path: Path) -> None:
    narrator = _CountingNarrator()
    grader = ModelGrader(cast(anthropic.Anthropic, _FailingAnthropic()))
    out_dir = tmp_path / "out"
    err = io.StringIO()
    code = main(
        [
            *("--variant", "baseline", "--case", TEXAS_CHAMPION, "--samples", "2"),
            *("--max-calls", "6", "--out", str(out_dir)),
        ],
        environ={"ANTHROPIC_API_KEY": NOT_A_KEY},
        env_file=NO_ENV_FILE,
        narrator=narrator,
        grader=grader,
        out=io.StringIO(),
        err=err,
    )
    assert code == EXIT_TRANSPORT_ERRORS
    warnings = [line for line in err.getvalue().splitlines() if "WARNING" in line]
    assert len(warnings) == 1 and "2 grader" in warnings[0]
    report = json.loads((out_dir / "report.json").read_text())
    assert report["errors"] == {"narrator": 0, "grader": 2}
    (variant,) = report["variants"]
    assert variant["narrator_errors"] == 0
    assert variant["grader_errors"] == 2
    assert variant["ungraded"] == 2 and variant["graded"] == 0
    assert variant["narrator_served"] == 2
    assert variant["metrics"]["first_try_rate"]["value"] == 1.0
    assert variant["metrics"]["mean_voice_score"]["value"] is None
    assert variant["per_case"][0]["grader_errors"] == 2
    markdown = (out_dir / "report.md").read_text()
    assert "TRANSPORT ERRORS" in markdown
    assert "| grader errors (ungraded) | 2 |" in markdown.splitlines()
    (first, _) = [json.loads(line) for line in (out_dir / "records.jsonl").read_text().splitlines()]
    assert first["served_by"] == "first"
    assert "APIConnectionError" in first["grade"]["transport_error"]


def test_hand_built_errors_stay_out_of_every_denominator() -> None:
    records = [
        _hrecord(variant="v", sample=0, served_by="first", score=8, case_id="case-a"),
        _hrecord(variant="v", sample=0, served_by="error", score=None, case_id="case-b"),
        _hrecord(variant="v", sample=1, served_by="first", score=6, case_id="case-a"),
        _hrecord(
            variant="v",
            sample=1,
            served_by="retry",
            score=None,
            case_id="case-b",
            grader_error=True,
        ),
    ]
    report = _report_json(records, ["v"], samples=2)
    assert report["errors"] == {"narrator": 1, "grader": 1}
    (variant,) = report["variants"]
    metrics = variant["metrics"]
    assert variant["narrations"] == 4
    assert variant["narrator_errors"] == 1 and variant["grader_errors"] == 1
    assert metrics["first_try_rate"] == {"value": 2 / 3, "min": 0.5, "max": 1.0}
    assert metrics["fallback_rate"] == {"value": 0.0, "min": 0.0, "max": 0.0}
    assert metrics["banned_word_rate"]["value"] == 0.0
    assert metrics["mean_voice_score"] == {"value": 7.0, "min": 6.0, "max": 8.0}
    assert metrics["ungraded"] == {"value": 1, "min": 0, "max": 1}


# ---------------------------------------------------------------------------
# the budget
# ---------------------------------------------------------------------------


def test_the_worst_case_estimate() -> None:
    assert worst_case_calls(cases=11, samples=2, variants=2) == 132
    assert worst_case_calls(cases=1, samples=1, variants=1) == 3


def test_the_budget_is_a_hard_cap() -> None:
    budget = CallBudget(max_calls=2)
    budget.spend("narrator")
    budget.spend("grader")
    with pytest.raises(BudgetExhausted):
        budget.spend("narrator")
    assert (budget.narrator_calls, budget.grader_calls, budget.used) == (1, 1, 2)


def test_max_calls_refuses_an_over_budget_estimate(tmp_path: Path) -> None:
    narrator, grader = _CountingNarrator(), _FakeGrader()
    err = io.StringIO()
    out_dir = tmp_path / "out"
    code = main(
        ["--variant", "baseline", "--samples", "2", "--max-calls", "65", "--out", str(out_dir)],
        environ={"ANTHROPIC_API_KEY": NOT_A_KEY},
        env_file=NO_ENV_FILE,
        narrator=narrator,
        grader=grader,
        out=io.StringIO(),
        err=err,
    )
    assert code == 2
    assert "66" in err.getvalue() and "65" in err.getvalue()
    assert narrator.calls == 0 and grader.calls == []
    assert not out_dir.exists()


def test_a_run_inside_the_budget_writes_the_three_files(tmp_path: Path) -> None:
    narrator, grader = _CountingNarrator(), _FakeGrader()
    out_dir = tmp_path / "out"
    code = main(
        [
            "--variant",
            "baseline",
            "--variant",
            "degraded",
            "--case",
            TEXAS_CHAMPION,
            "--samples",
            "1",
            "--max-calls",
            "6",
            "--out",
            str(out_dir),
        ],
        environ={"ANTHROPIC_API_KEY": NOT_A_KEY},
        env_file=NO_ENV_FILE,
        narrator=narrator,
        grader=grader,
        out=io.StringIO(),
        err=io.StringIO(),
    )
    assert code == 0
    assert narrator.calls == 2 and len(grader.calls) == 2
    report = json.loads((out_dir / "report.json").read_text())
    assert report["complete"] is True
    assert [variant["name"] for variant in report["variants"]] == ["baseline", "degraded"]
    lines = (out_dir / "records.jsonl").read_text().splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["variant"] == "baseline"
    assert first["case"] == TEXAS_CHAMPION
    assert first["prompt_version"] == PROMPT_VERSION
    assert first["grounding_version"] == GROUNDING_VERSION
    assert first["narrator_model"] == MODEL
    assert first["grader_model"] == GRADER_MODEL
    assert first["attempts"][0]["tool_input"] == {"text": "Solid case, no notes.", "claims": []}
    assert first["attempts"][0]["errors"] == []
    assert first["served_text"] == "Solid case, no notes."
    assert first["grade"]["score"] == 7
    assert "baseline" in (out_dir / "report.md").read_text()


def test_the_run_stops_at_the_cap_mid_run_with_a_partial_report(
    tmp_path: Path, dataset: tuple[EvalCase, ...]
) -> None:
    narrator, grader = _CountingNarrator(), _FakeGrader()
    out_dir = tmp_path / "out"
    report = run_to_directory(
        cases=dataset[:3],
        variants=[baseline_variant()],
        samples=1,
        narrator=narrator,
        grader=grader,
        max_calls=5,
        worst_case_estimate=9,
        out_dir=out_dir,
    )
    # two narrations (a narrator call and a grader call each), then the cap
    assert narrator.calls + len(grader.calls) <= 5
    assert narrator.calls == 3 and len(grader.calls) == 2
    assert report.complete is False
    written = json.loads((out_dir / "report.json").read_text())
    assert written["complete"] is False
    assert "5" in written["stop_note"]
    assert written["variants"][0]["narrations"] == 2
    assert len((out_dir / "records.jsonl").read_text().splitlines()) == 2
    assert "PARTIAL RUN" in (out_dir / "report.md").read_text()


# ---------------------------------------------------------------------------
# safety
# ---------------------------------------------------------------------------


def test_the_default_env_file_is_apps_api_dot_env() -> None:
    assert DEFAULT_ENV_FILE == TESTS_DIR.parent / ".env"


def test_an_existing_env_file_is_refused(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("# stand-in for apps/api/.env\n")
    for live in (True, False):
        refusals = preflight_refusals(
            environ={"ANTHROPIC_API_KEY": NOT_A_KEY}, env_file=env_file, live=live
        )
        assert any(".env" in refusal for refusal in refusals)
    narrator, grader = _CountingNarrator(), _FakeGrader()
    code = main(
        ["--variant", "baseline", "--samples", "1", "--max-calls", "99", "--out", str(tmp_path)],
        environ={"ANTHROPIC_API_KEY": NOT_A_KEY},
        env_file=env_file,
        narrator=narrator,
        grader=grader,
        out=io.StringIO(),
        err=io.StringIO(),
    )
    assert code == 2
    assert narrator.calls == 0 and grader.calls == []


@pytest.mark.parametrize("variable", ["DATABASE_URL", "MY_TEAM_IS_BETTER_API_ENV_FILE"])
def test_a_set_database_or_env_file_variable_is_refused(variable: str, tmp_path: Path) -> None:
    environ = {"ANTHROPIC_API_KEY": NOT_A_KEY, variable: ""}
    for live in (True, False):
        refusals = preflight_refusals(environ=environ, env_file=NO_ENV_FILE, live=live)
        assert any(variable in refusal for refusal in refusals)
    narrator, grader = _CountingNarrator(), _FakeGrader()
    err = io.StringIO()
    code = main(
        ["--variant", "baseline", "--samples", "1", "--max-calls", "99", "--out", str(tmp_path)],
        environ=environ,
        env_file=NO_ENV_FILE,
        narrator=narrator,
        grader=grader,
        out=io.StringIO(),
        err=err,
    )
    assert code == 2
    assert variable in err.getvalue()
    assert narrator.calls == 0 and grader.calls == []


def test_an_unset_key_is_refused_for_a_live_run(tmp_path: Path) -> None:
    for environ in ({}, {"ANTHROPIC_API_KEY": ""}):
        refusals = preflight_refusals(environ=environ, env_file=NO_ENV_FILE, live=True)
        assert any("ANTHROPIC_API_KEY" in refusal for refusal in refusals)
        assert preflight_refusals(environ=environ, env_file=NO_ENV_FILE, live=False) == []
    narrator, grader = _CountingNarrator(), _FakeGrader()
    code = main(
        ["--variant", "baseline", "--samples", "1", "--max-calls", "99", "--out", str(tmp_path)],
        environ={},
        env_file=NO_ENV_FILE,
        narrator=narrator,
        grader=grader,
        out=io.StringIO(),
        err=io.StringIO(),
    )
    assert code == 2
    assert narrator.calls == 0 and grader.calls == []
    assert (
        preflight_refusals(
            environ={"ANTHROPIC_API_KEY": NOT_A_KEY}, env_file=NO_ENV_FILE, live=True
        )
        == []
    )


def test_a_refusal_happens_before_api_config_is_imported() -> None:
    """`api.config` loads apps/api/.env at import, so the checks run first.
    In a fresh interpreter, a refused run leaves `api.config` unimported. The
    environment here is a plain dict handed to `main`, not the process's."""
    script = (
        "import sys\n"
        "from pathlib import Path\n"
        "from persona_eval_harness.cli import main\n"
        "assert 'api.config' not in sys.modules\n"
        "code = main(['--dry-run'], environ={'DATABASE_URL': ''},\n"
        "            env_file=Path('/nonexistent/.env'))\n"
        "print(code, 'api.config' in sys.modules)\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=TESTS_DIR.parent,
        env={"PYTHONPATH": str(TESTS_DIR), "PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip().splitlines()[-1] == "2 False"


# ---------------------------------------------------------------------------
# --dry-run
# ---------------------------------------------------------------------------


def test_dry_run_makes_no_calls_and_needs_no_key(tmp_path: Path) -> None:
    narrator, grader = _CountingNarrator(), _FakeGrader()
    out = io.StringIO()
    code = main(
        ["--dry-run", "--variant", "baseline", "--variant", "degraded", "--samples", "2"],
        environ={},
        env_file=NO_ENV_FILE,
        narrator=narrator,
        grader=grader,
        out=out,
        err=io.StringIO(),
    )
    assert code == 0
    assert narrator.calls == 0 and grader.calls == []
    printed = out.getvalue()
    for spec in CASE_SPECS:
        assert spec.id in printed
    assert "baseline" in printed and "degraded" in printed
    assert "132" in printed
    assert list(tmp_path.iterdir()) == []
