"""Runs the dataset through each variant, N times, and grades every narration.

One narration is production's path with only the system prompt swapped:

    narrate()  ->  SystemSwappingNarrator  ->  RecordingNarrator
               ->  BudgetedNarrator        ->  ErrorRecordingNarrator
               ->  the real (or fake) narrator

`narrate()` is `api.persona.narrate.narrate` itself, called with the fact
block, contested flag, catalog and fallback text production's service would
pass, so what is served (the validator's rendering, a retry, the fallback)
is exactly what a user would see under that prompt. The code graders then
re-judge the recorded calls (`fixtures.persona_eval.judge_narration`,
`build_record`) and the model grader grades the served text, fallbacks
included.

**A narrator transport error is not the variant's fallback.** Production
`narrate()` answers an `anthropic.APIStatusError` or `APIConnectionError`
(once the SDK's own retries are spent) with the fallback, which would read
as the variant's own fallback and move every rate. `ErrorRecordingNarrator`
sits next to the real narrator, records any exception the call raises and
re-raises it, so production still sees the error. When `narrate()` then
returns, the swallowed error makes the narration the `error` outcome
(`HarnessRecord.served_by`): no grader call, no grade, and `report.py`
leaves it out of every rate and mean and counts it instead.

**The QB narrator** (issue #463) runs the same way through production's QB
entry point, `api.persona.service.narrate_qb_comparison` (which runs
`narrate_checked` with the QB prompt and `check_and_render_qb`), with the
cache disabled so every narration calls the narrator. `judge_qb_narration`
re-checks the recorded calls with `check_and_render_qb` to say which one was
served (first, retry, fallback or untraceable), and the QB code graders
(`qb_graders.py`) score the served narration.

**Usage.** Every record keeps each narrator call's token usage (and the
grade keeps the grader's), so the report and records.jsonl can price a
narration (`cost.py`).

The loops go sample, then variant, then case, so a run stopped at the
`--max-calls` cap has covered the variants evenly.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TextIO

from anthropic.types import MessageParam
from fixtures.persona_eval import (
    JudgedCall,
    Judgement,
    NarrationRecord,
    RecordedCall,
    RecordingNarrator,
    ServedBy,
    banned_hits,
    build_record,
    judge_narration,
    length_violations,
    named_team_violations,
)

from api.persona.budget import UnlimitedCallBudget
from api.persona.cache import DisabledNarrationCache
from api.persona.claims import TOOL_NAME
from api.persona.claude_client import Narrator, NarratorReply, TokenUsage
from api.persona.narrate import narrate
from api.persona.qb_claims import check_and_render_qb
from api.persona.service import narrate_qb_comparison
from persona_eval_harness.budget import BudgetedNarrator, BudgetExhausted, CallBudget
from persona_eval_harness.dataset import EvalCase
from persona_eval_harness.grader import Grade, Grader
from persona_eval_harness.qb_dataset import QbEvalCase
from persona_eval_harness.qb_graders import QbGrades, grade_qb
from persona_eval_harness.report import (
    Report,
    RunContext,
    build_report,
    record_to_json,
    render_markdown,
    report_to_json,
    transport_error_warning,
)
from persona_eval_harness.variants import SystemSwappingNarrator, Variant

# `fixtures.persona_eval.ServedBy`, plus the harness's own `error`: the
# narrator call raised and production served the fallback because of it.
Outcome = ServedBy | Literal["error"]


class ErrorRecordingNarrator:
    """A pass-through that records every exception the inner narrator raises,
    then re-raises it unchanged, so production `narrate()` handles it exactly
    as it would without the harness. An exception `narrate()` doesn't swallow
    ends the run, so on a narration that returned, every recorded error is
    one production answered with the fallback: a transport error."""

    def __init__(self, inner: Narrator) -> None:
        self._inner = inner
        self.errors: list[Exception] = []

    def submit(self, *, system: str, messages: list[MessageParam]) -> NarratorReply:
        try:
            return self._inner.submit(system=system, messages=messages)
        except Exception as exc:
            self.errors.append(exc)
            raise


@dataclass(frozen=True)
class HarnessRecord:
    """One narration. `claims` is the served call's claim count (None when
    the narrator didn't serve it); `property_violations` are §8 properties 1
    (champion and team-case cases only), 3 and 4 on a narrator-served text;
    `banned` is every banned-word hit in the served text.

    `narrator_error` ("ExceptionType: message") is set when a narrator call
    raised a transport error; such a narration is `served_by == "error"` and
    `grade` is None, because it was never graded. Otherwise `grade` is set,
    and may itself be an ungraded result, a grader transport error included
    (`grader_error`).

    `narrator_usage` is each returned narrator call's usage, in order (`None`
    for a fake's reply); `qb_grades` is set on a QB narration only."""

    variant: str
    case_id: str
    sample: int
    narration: NarrationRecord
    claims: int | None
    property_violations: tuple[str, ...]
    banned: tuple[str, ...]
    grade: Grade | None
    narrator_error: str | None = None
    narrator_usage: tuple[TokenUsage | None, ...] = ()
    qb_grades: QbGrades | None = None

    @property
    def errored(self) -> bool:
        return self.narrator_error is not None

    @property
    def grader_error(self) -> bool:
        return self.grade is not None and self.grade.transport_error is not None

    @property
    def served_by(self) -> Outcome:
        return "error" if self.errored else self.narration.served_by

    @property
    def served_text(self) -> str:
        return self.narration.judgement.served_text


@dataclass(frozen=True)
class RunResult:
    records: tuple[HarnessRecord, ...]
    complete: bool
    stop_note: str | None
    narrator_calls: int
    grader_calls: int


def served_claims(judgement: Judgement) -> int | None:
    served = judgement.served_attempt
    if served is None or judgement.served_by not in ("first", "retry"):
        return None
    tool_input = served.call.tool_input
    claims = tool_input.get("claims") if isinstance(tool_input, dict) else None
    return len(claims) if isinstance(claims, list) else 0


def property_violations(case: EvalCase | QbEvalCase, judgement: Judgement) -> tuple[str, ...]:
    """§8 properties 1, 3 and 4 where they apply. Properties 2 and 5 are the
    judgement's `served_by`. Only a narrator-served text is checked: the
    fallback is a template."""
    if judgement.served_by not in ("first", "retry"):
        return ()
    text = judgement.served_text
    violations: list[str] = []
    # Property 1 (the expected team is named) is a team verdict's only.
    expected_team = case.spec.expected_team if isinstance(case, EvalCase) else None
    if isinstance(case, EvalCase) and expected_team is not None:
        violations += named_team_violations(
            text, expected_team, [record.name for record in case.catalog]
        )
    violations += length_violations(text)
    hits = banned_hits(text)
    if hits:
        violations.append(f"banned-words: {hits}")
    return tuple(violations)


def narrate_case(
    *,
    case: EvalCase,
    variant: Variant,
    sample: int,
    narrator: Narrator,
    grader: Grader,
    budget: CallBudget,
) -> HarnessRecord:
    """Narrate, judge and grade one case under one variant. Raises
    `BudgetExhausted` when the cap is reached part-way. A narration whose
    narrator call raised is returned ungraded, as the `error` outcome."""
    errors = ErrorRecordingNarrator(narrator)
    recorder = RecordingNarrator(BudgetedNarrator(errors, budget))
    swapped = SystemSwappingNarrator(recorder, system=variant.build_system_prompt(case.user_team))
    result = narrate(
        fact_block_json=case.fact_block_json,
        user_team=case.user_team,
        contested=case.contested,
        catalog=case.catalog,
        narrator=swapped,
        fallback_text=case.fallback_text,
        # The harness caps its own calls (`--max-calls`, BudgetedNarrator).
        budget=UnlimitedCallBudget(),
    )
    judgement = judge_narration(
        served_text=result.text,
        calls=recorder.recorded_calls(),
        catalog=case.catalog,
        fallback_text=case.fallback_text,
    )
    narrator_error = (
        "; ".join(f"{type(exc).__name__}: {exc}" for exc in errors.errors)
        if errors.errors
        else None
    )
    grade: Grade | None = None
    if narrator_error is None:
        budget.spend("grader")
        grade = grader.grade(
            fact_block_json=case.fact_block_json, contested=case.contested, narration=result.text
        )
    return HarnessRecord(
        variant=variant.name,
        case_id=case.id,
        sample=sample,
        narration=build_record(f"{variant.name} {case.id} sample {sample + 1}", judgement),
        claims=served_claims(judgement),
        property_violations=property_violations(case, judgement),
        banned=tuple(banned_hits(result.text)),
        grade=grade,
        narrator_error=narrator_error,
        narrator_usage=tuple(reply.usage for reply in recorder.replies),
    )


def judge_qb_narration(
    *,
    served_text: str,
    replies: Sequence[NarratorReply],
    case: QbEvalCase,
) -> Judgement:
    """Which recorded QB call production served, re-checked with
    `check_and_render_qb` exactly as `narrate_checked` checks it: the first
    valid call whose rendering is the served text is first or retry, the
    fallback text is the fallback, anything else is untraceable. Violations
    are left empty: the QB graders are the QB code checks."""
    attempts: list[JudgedCall] = []
    for reply in replies:
        call = RecordedCall(
            tool_input=None if reply.tool_call is None else reply.tool_call.input,
            fact_block_json=case.fact_block_json,
            stop_reason=reply.stop_reason,
        )
        if call.tool_input is None:
            error = f"no {TOOL_NAME} call came back (stop reason: {call.stop_reason})"
            attempts.append(JudgedCall(call=call, errors=(error,), text=None))
            continue
        outcome = check_and_render_qb(call.tool_input, case.fact_block_json, case.player_names)
        attempts.append(JudgedCall(call=call, errors=outcome.errors, text=outcome.text))
    served_index = next(
        (i for i, attempt in enumerate(attempts) if attempt.valid and attempt.text == served_text),
        None,
    )
    served_by: ServedBy
    if served_text == case.fallback_text:
        served_by = "fallback"
    elif served_index is None:
        served_by = "untraceable"
    else:
        served_by = "first" if served_index == 0 else "retry"
    return Judgement(
        served_text=served_text,
        attempts=tuple(attempts),
        served_by=served_by,
        served_attempt=None if served_index is None else attempts[served_index],
        violations=(),
    )


def narrate_qb_case(
    *,
    case: QbEvalCase,
    variant: Variant,
    sample: int,
    narrator: Narrator,
    grader: Grader,
    budget: CallBudget,
) -> HarnessRecord:
    """`narrate_case` for a QB case, through production's
    `narrate_qb_comparison` with the cache disabled."""
    errors = ErrorRecordingNarrator(narrator)
    recorder = RecordingNarrator(BudgetedNarrator(errors, budget))
    swapped = SystemSwappingNarrator(recorder, system=variant.build_system_prompt(case.user_team))
    served = narrate_qb_comparison(
        case.evidence,
        player_names=case.player_names,
        cache=DisabledNarrationCache(),
        narrator=swapped,
        # The harness caps its own calls (`--max-calls`, BudgetedNarrator).
        budget=UnlimitedCallBudget(),
    )
    judgement = judge_qb_narration(served_text=served.text, replies=recorder.replies, case=case)
    narrator_error = (
        "; ".join(f"{type(exc).__name__}: {exc}" for exc in errors.errors)
        if errors.errors
        else None
    )
    grade: Grade | None = None
    if narrator_error is None:
        budget.spend("grader")
        grade = grader.grade(
            fact_block_json=case.fact_block_json, contested=False, narration=served.text
        )
    served_attempt = judgement.served_attempt
    return HarnessRecord(
        variant=variant.name,
        case_id=case.id,
        sample=sample,
        narration=build_record(f"{variant.name} {case.id} sample {sample + 1}", judgement),
        claims=served_claims(judgement),
        property_violations=property_violations(case, judgement),
        banned=tuple(banned_hits(served.text)),
        grade=grade,
        narrator_error=narrator_error,
        narrator_usage=tuple(reply.usage for reply in recorder.replies),
        qb_grades=grade_qb(
            served_text=served.text,
            served_input=None if served_attempt is None else served_attempt.call.tool_input,
            fact_block_json=case.fact_block_json,
        ),
    )


def run_eval(
    *,
    cases: Sequence[EvalCase | QbEvalCase],
    variants: Sequence[Variant],
    samples: int,
    narrator: Narrator,
    grader: Grader,
    budget: CallBudget,
    on_record: Callable[[HarnessRecord], None] | None = None,
) -> RunResult:
    records: list[HarnessRecord] = []
    for sample in range(samples):
        for variant in variants:
            for case in cases:
                try:
                    if isinstance(case, QbEvalCase):
                        record = narrate_qb_case(
                            case=case,
                            variant=variant,
                            sample=sample,
                            narrator=narrator,
                            grader=grader,
                            budget=budget,
                        )
                    else:
                        record = narrate_case(
                            case=case,
                            variant=variant,
                            sample=sample,
                            narrator=narrator,
                            grader=grader,
                            budget=budget,
                        )
                except BudgetExhausted as exc:
                    note = (
                        f"Stopped mid-run: {exc}. The narration in progress ({variant.name}, "
                        f"{case.id}, sample {sample + 1}) was discarded; "
                        f"{len(records)} narrations finished."
                    )
                    return RunResult(
                        records=tuple(records),
                        complete=False,
                        stop_note=note,
                        narrator_calls=budget.narrator_calls,
                        grader_calls=budget.grader_calls,
                    )
                records.append(record)
                if on_record is not None:
                    on_record(record)
    return RunResult(
        records=tuple(records),
        complete=True,
        stop_note=None,
        narrator_calls=budget.narrator_calls,
        grader_calls=budget.grader_calls,
    )


def _progress_line(record: HarnessRecord) -> str:
    head = (
        f"[harness] {record.variant} {record.case_id} sample {record.sample + 1}: "
        f"served={record.served_by} calls={record.narration.claude_calls} "
    )
    grade = record.grade
    if grade is None:
        return f"{head}narrator error ({record.narrator_error}), not graded"
    score = grade.score if grade.graded else f"ungraded ({grade.ungraded_reason})"
    return f"{head}claims={record.claims} score={score} contradictions={len(grade.contradictions)}"


def run_to_directory(
    *,
    cases: Sequence[EvalCase | QbEvalCase],
    variants: Sequence[Variant],
    samples: int,
    narrator: Narrator,
    grader: Grader,
    max_calls: int,
    worst_case_estimate: int,
    out_dir: Path,
    progress: TextIO | None = None,
    context: RunContext | None = None,
) -> Report:
    """Run under a `max_calls` budget, appending each record to
    `records.jsonl` as it finishes, then write `report.json` and `report.md`
    (marked partial when the cap stopped the run)."""
    context = context or RunContext()
    out_dir.mkdir(parents=True, exist_ok=True)
    budget = CallBudget(max_calls)
    with (out_dir / "records.jsonl").open("w", encoding="utf-8") as records_file:

        def on_record(record: HarnessRecord) -> None:
            line = json.dumps(
                record_to_json(record, samples=samples, context=context), default=repr
            )
            records_file.write(line + "\n")
            records_file.flush()
            if progress is not None:
                print(_progress_line(record), file=progress, flush=True)

        result = run_eval(
            cases=cases,
            variants=variants,
            samples=samples,
            narrator=narrator,
            grader=grader,
            budget=budget,
            on_record=on_record,
        )
    report = build_report(
        records=result.records,
        variants=variants,
        case_ids=[case.id for case in cases],
        samples=samples,
        complete=result.complete,
        stop_note=result.stop_note,
        narrator_calls=result.narrator_calls,
        grader_calls=result.grader_calls,
        max_calls=max_calls,
        worst_case_estimate=worst_case_estimate,
        context=context,
    )
    (out_dir / "report.json").write_text(
        json.dumps(report_to_json(report), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (out_dir / "report.md").write_text(render_markdown(report), encoding="utf-8")
    if progress is not None and result.stop_note is not None:
        print(f"[harness] {result.stop_note}", file=progress, flush=True)
    warning = transport_error_warning(report)
    if progress is not None and warning is not None:
        print(f"[harness] WARNING: {warning}", file=progress, flush=True)
    return report
