"""Runs the dataset through each variant, N times, and grades every narration.

One narration is production's path with only the system prompt swapped:

    narrate()  ->  SystemSwappingNarrator  ->  RecordingNarrator
               ->  BudgetedNarrator        ->  the real (or fake) narrator

`narrate()` is `api.persona.narrate.narrate` itself, called with the fact
block, contested flag, catalog and fallback text production's service would
pass, so what is served (the validator's rendering, a retry, the fallback)
is exactly what a user would see under that prompt. The code graders then
re-judge the recorded calls (`fixtures.persona_eval.judge_narration`,
`build_record`) and the model grader grades the served text, fallbacks
included.

The loops go sample, then variant, then case, so a run stopped at the
`--max-calls` cap has covered the variants evenly.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from fixtures.persona_eval import (
    Judgement,
    NarrationRecord,
    RecordingNarrator,
    ServedBy,
    banned_hits,
    build_record,
    judge_narration,
    length_violations,
    named_team_violations,
)

from api.persona.claude_client import Narrator
from api.persona.narrate import narrate
from persona_eval_harness.budget import BudgetedNarrator, BudgetExhausted, CallBudget
from persona_eval_harness.dataset import EvalCase
from persona_eval_harness.grader import Grade, Grader
from persona_eval_harness.report import (
    Report,
    build_report,
    record_to_json,
    render_markdown,
    report_to_json,
)
from persona_eval_harness.variants import SystemSwappingNarrator, Variant


@dataclass(frozen=True)
class HarnessRecord:
    """One graded narration. `claims` is the served call's claim count (None
    when the narrator didn't serve it); `property_violations` are §8
    properties 1 (champion and team-case cases only), 3 and 4 on a
    narrator-served text; `banned` is every banned-word hit in the served
    text."""

    variant: str
    case_id: str
    sample: int
    narration: NarrationRecord
    claims: int | None
    property_violations: tuple[str, ...]
    banned: tuple[str, ...]
    grade: Grade

    @property
    def served_by(self) -> ServedBy:
        return self.narration.served_by

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


def property_violations(case: EvalCase, judgement: Judgement) -> tuple[str, ...]:
    """§8 properties 1, 3 and 4 where they apply. Properties 2 and 5 are the
    judgement's `served_by`. Only a narrator-served text is checked: the
    fallback is a template."""
    if judgement.served_by not in ("first", "retry"):
        return ()
    text = judgement.served_text
    violations: list[str] = []
    expected_team = case.spec.expected_team
    if expected_team is not None:
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
    `BudgetExhausted` when the cap is reached part-way."""
    recorder = RecordingNarrator(BudgetedNarrator(narrator, budget))
    swapped = SystemSwappingNarrator(recorder, system=variant.build_system_prompt(case.user_team))
    result = narrate(
        fact_block_json=case.fact_block_json,
        user_team=case.user_team,
        contested=case.contested,
        catalog=case.catalog,
        narrator=swapped,
        fallback_text=case.fallback_text,
    )
    judgement = judge_narration(
        served_text=result.text,
        calls=recorder.recorded_calls(),
        catalog=case.catalog,
        fallback_text=case.fallback_text,
    )
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
    )


def run_eval(
    *,
    cases: Sequence[EvalCase],
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
    grade = record.grade
    score = grade.score if grade.graded else f"ungraded ({grade.ungraded_reason})"
    return (
        f"[harness] {record.variant} {record.case_id} sample {record.sample + 1}: "
        f"served={record.served_by} calls={record.narration.claude_calls} "
        f"claims={record.claims} score={score} contradictions={len(grade.contradictions)}"
    )


def run_to_directory(
    *,
    cases: Sequence[EvalCase],
    variants: Sequence[Variant],
    samples: int,
    narrator: Narrator,
    grader: Grader,
    max_calls: int,
    worst_case_estimate: int,
    out_dir: Path,
    progress: TextIO | None = None,
) -> Report:
    """Run under a `max_calls` budget, appending each record to
    `records.jsonl` as it finishes, then write `report.json` and `report.md`
    (marked partial when the cap stopped the run)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    budget = CallBudget(max_calls)
    with (out_dir / "records.jsonl").open("w", encoding="utf-8") as records_file:

        def on_record(record: HarnessRecord) -> None:
            line = json.dumps(record_to_json(record, samples=samples), default=repr)
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
    )
    (out_dir / "report.json").write_text(
        json.dumps(report_to_json(report), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (out_dir / "report.md").write_text(render_markdown(report), encoding="utf-8")
    if progress is not None and result.stop_note is not None:
        print(f"[harness] {result.stop_note}", file=progress, flush=True)
    return report
