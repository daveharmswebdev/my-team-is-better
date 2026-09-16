"""Aggregation, spread and the report files.

Every metric is computed twice per variant: once over all its narrations
(`value`), and once per sample round (sample 1 of every case, sample 2 of
every case, ...), whose smallest and largest values are the `min`/`max`
spread. Two variants whose ranges overlap differ by no more than run-to-run
noise, and `report.md` says so metric by metric.

Denominators, so a rate is never read against the wrong base:

- first try / retry / fallback / untraceable: all narrations;
- claims, timing/venue, ambiguous when, over three sentences, §8 property
  1/3/4 violations: narrations the narrator served (first or retry);
- lowercase block-team rejections: all narrator attempts;
- banned words: all narrations;
- mean voice score and contradictions: graded narrations; `ungraded` is a
  count.

A metric with an empty denominator is `None` (`n/a`), never 0.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Literal

from fixtures.persona_eval import PROMPT_MAX_SENTENCES, rate, summarize

from api.config import PROMPT_VERSION
from api.persona.claims import GROUNDING_VERSION
from api.persona.claude_client import MODEL
from persona_eval_harness.grader import GRADER_MODEL, GRADER_PROMPT_VERSION

if TYPE_CHECKING:
    from persona_eval_harness.runner import HarnessRecord
    from persona_eval_harness.variants import Variant

Number = float | int
MetricKind = Literal["rate", "mean", "score", "count"]


def _mean(values: Sequence[Number]) -> float | None:
    return None if not values else sum(values) / len(values)


def _count_served(records: Sequence[HarnessRecord], served_by: str) -> float | None:
    return rate(sum(1 for record in records if record.served_by == served_by), len(records))


def _narrator_served(records: Sequence[HarnessRecord]) -> list[HarnessRecord]:
    return [record for record in records if record.narration.narrator_served]


def _graded(records: Sequence[HarnessRecord]) -> list[HarnessRecord]:
    return [record for record in records if record.grade.graded]


def _claims(records: Sequence[HarnessRecord]) -> float | None:
    return _mean(
        [record.claims for record in _narrator_served(records) if record.claims is not None]
    )


def _property_violation_rate(records: Sequence[HarnessRecord]) -> float | None:
    served = _narrator_served(records)
    return rate(sum(1 for record in served if record.property_violations), len(served))


def _mean_score(records: Sequence[HarnessRecord]) -> float | None:
    return _mean(
        [record.grade.score for record in _graded(records) if record.grade.score is not None]
    )


def _contradiction_rate(records: Sequence[HarnessRecord]) -> float | None:
    graded = _graded(records)
    return rate(sum(1 for record in graded if record.grade.contradictions), len(graded))


@dataclass(frozen=True)
class MetricDef:
    key: str
    label: str
    kind: MetricKind
    compute: Callable[[Sequence[HarnessRecord]], Number | None]


METRICS: tuple[MetricDef, ...] = (
    MetricDef(
        "first_try_rate", "first-try valid rate", "rate", lambda rs: _count_served(rs, "first")
    ),
    MetricDef("retry_rate", "retry rate", "rate", lambda rs: _count_served(rs, "retry")),
    MetricDef("fallback_rate", "fallback rate", "rate", lambda rs: _count_served(rs, "fallback")),
    MetricDef(
        "untraceable_rate",
        "untraceable rate",
        "rate",
        lambda rs: _count_served(rs, "untraceable"),
    ),
    MetricDef("claims_per_narration", "claims per served narration", "mean", _claims),
    MetricDef(
        "timing_venue_rate",
        "timing/venue wording rate",
        "rate",
        lambda rs: summarize([r.narration for r in rs]).timing_venue_rate,
    ),
    MetricDef(
        "ambiguous_when_rate",
        "ambiguous-when rate",
        "rate",
        lambda rs: summarize([r.narration for r in rs]).ambiguous_when_rate,
    ),
    MetricDef(
        "over_three_sentences_rate",
        f"over {PROMPT_MAX_SENTENCES} sentences rate",
        "rate",
        lambda rs: summarize([r.narration for r in rs]).over_prompt_length_rate,
    ),
    MetricDef(
        "lowercase_rejection_rate",
        "lowercase block-team rejection rate (of attempts)",
        "rate",
        lambda rs: summarize([r.narration for r in rs]).lowercase_rejection_rate,
    ),
    MetricDef(
        "property_violation_rate",
        "§8 property 1/3/4 violation rate",
        "rate",
        _property_violation_rate,
    ),
    MetricDef(
        "banned_word_rate",
        "banned-word rate",
        "rate",
        lambda rs: rate(sum(1 for r in rs if r.banned), len(rs)),
    ),
    MetricDef("mean_voice_score", "mean voice score (1-10)", "score", _mean_score),
    MetricDef("contradiction_rate", "contradiction rate (of graded)", "rate", _contradiction_rate),
    MetricDef(
        "ungraded",
        "ungraded (count)",
        "count",
        lambda rs: sum(1 for r in rs if not r.grade.graded) if rs else None,
    ),
)


@dataclass(frozen=True)
class MetricValue:
    value: Number | None
    min: Number | None
    max: Number | None


@dataclass(frozen=True)
class CaseBreakdown:
    case: str
    narrations: int
    first: int
    retry: int
    fallback: int
    untraceable: int
    claims_per_narration: float | None
    mean_voice_score: float | None
    contradiction_narrations: int
    graded: int
    ungraded: int


@dataclass(frozen=True)
class VariantReport:
    name: str
    source: str
    narrations: int
    narrator_served: int
    graded: int
    ungraded: int
    sample_rounds: int
    metrics: dict[str, MetricValue]
    per_case: tuple[CaseBreakdown, ...]


@dataclass(frozen=True)
class Report:
    prompt_version: str
    grounding_version: str
    narrator_model: str
    grader_model: str
    grader_prompt_version: str
    samples: int
    cases: tuple[str, ...]
    complete: bool
    stop_note: str | None
    narrator_calls: int
    grader_calls: int
    max_calls: int
    worst_case_estimate: int
    variants: tuple[VariantReport, ...]


def metric_value(metric: MetricDef, records: Sequence[HarnessRecord]) -> MetricValue:
    """`metric` over all `records`, with its min-max over the sample rounds
    present in them."""
    rounds = sorted({record.sample for record in records})
    per_round = [
        value
        for sample in rounds
        if (value := metric.compute([r for r in records if r.sample == sample])) is not None
    ]
    return MetricValue(
        value=metric.compute(records) if records else None,
        min=min(per_round) if per_round else None,
        max=max(per_round) if per_round else None,
    )


def _case_breakdown(case_id: str, records: Sequence[HarnessRecord]) -> CaseBreakdown:
    graded = _graded(records)
    return CaseBreakdown(
        case=case_id,
        narrations=len(records),
        first=sum(1 for r in records if r.served_by == "first"),
        retry=sum(1 for r in records if r.served_by == "retry"),
        fallback=sum(1 for r in records if r.served_by == "fallback"),
        untraceable=sum(1 for r in records if r.served_by == "untraceable"),
        claims_per_narration=_claims(records),
        mean_voice_score=_mean_score(records),
        contradiction_narrations=sum(1 for r in graded if r.grade.contradictions),
        graded=len(graded),
        ungraded=len(records) - len(graded),
    )


def variant_report(
    variant: Variant, records: Sequence[HarnessRecord], case_ids: Sequence[str]
) -> VariantReport:
    mine = [record for record in records if record.variant == variant.name]
    graded = _graded(mine)
    return VariantReport(
        name=variant.name,
        source=variant.source,
        narrations=len(mine),
        narrator_served=len(_narrator_served(mine)),
        graded=len(graded),
        ungraded=len(mine) - len(graded),
        sample_rounds=len({record.sample for record in mine}),
        metrics={metric.key: metric_value(metric, mine) for metric in METRICS},
        per_case=tuple(
            _case_breakdown(case_id, [r for r in mine if r.case_id == case_id])
            for case_id in case_ids
        ),
    )


def build_report(
    *,
    records: Sequence[HarnessRecord],
    variants: Sequence[Variant],
    case_ids: Sequence[str],
    samples: int,
    complete: bool,
    stop_note: str | None,
    narrator_calls: int,
    grader_calls: int,
    max_calls: int,
    worst_case_estimate: int,
) -> Report:
    return Report(
        prompt_version=PROMPT_VERSION,
        grounding_version=GROUNDING_VERSION,
        narrator_model=MODEL,
        grader_model=GRADER_MODEL,
        grader_prompt_version=GRADER_PROMPT_VERSION,
        samples=samples,
        cases=tuple(case_ids),
        complete=complete,
        stop_note=stop_note,
        narrator_calls=narrator_calls,
        grader_calls=grader_calls,
        max_calls=max_calls,
        worst_case_estimate=worst_case_estimate,
        variants=tuple(variant_report(variant, records, case_ids) for variant in variants),
    )


def report_to_json(report: Report) -> dict[str, object]:
    return {
        "prompt_version": report.prompt_version,
        "grounding_version": report.grounding_version,
        "narrator_model": report.narrator_model,
        "grader_model": report.grader_model,
        "grader_prompt_version": report.grader_prompt_version,
        "samples": report.samples,
        "cases": list(report.cases),
        "complete": report.complete,
        "stop_note": report.stop_note,
        "calls": {
            "narrator": report.narrator_calls,
            "grader": report.grader_calls,
            "total": report.narrator_calls + report.grader_calls,
            "max_calls": report.max_calls,
            "worst_case_estimate": report.worst_case_estimate,
        },
        "variants": [
            {
                "name": variant.name,
                "source": variant.source,
                "narrations": variant.narrations,
                "narrator_served": variant.narrator_served,
                "graded": variant.graded,
                "ungraded": variant.ungraded,
                "sample_rounds": variant.sample_rounds,
                "metrics": {key: asdict(value) for key, value in variant.metrics.items()},
                "per_case": [asdict(case) for case in variant.per_case],
            }
            for variant in report.variants
        ],
    }


def record_to_json(record: HarnessRecord, *, samples: int) -> dict[str, object]:
    """One `records.jsonl` line: the run's keys, every attempt's raw tool
    input and validator errors, the served text, the measurements and the
    grader's whole output."""
    judgement = record.narration.judgement
    grade = record.grade
    return {
        "prompt_version": PROMPT_VERSION,
        "grounding_version": GROUNDING_VERSION,
        "narrator_model": MODEL,
        "grader_model": GRADER_MODEL,
        "grader_prompt_version": GRADER_PROMPT_VERSION,
        "samples": samples,
        "variant": record.variant,
        "case": record.case_id,
        "sample": record.sample + 1,
        "served_by": record.served_by,
        "served_text": record.served_text,
        "claude_calls": record.narration.claude_calls,
        "claims": record.claims,
        "attempts": [
            {
                "tool_input": attempt.call.tool_input,
                "stop_reason": attempt.call.stop_reason,
                "errors": list(attempt.errors),
                "rendered": attempt.text,
            }
            for attempt in judgement.attempts
        ],
        "judge_violations": list(judgement.violations),
        "sentences": record.narration.sentences,
        "timing_venue": [asdict(flag) for flag in record.narration.timing_venue],
        "ambiguous_when": list(record.narration.ambiguous_when),
        "lowercase_rejections": record.narration.lowercase_rejections,
        "property_violations": list(record.property_violations),
        "banned": list(record.banned),
        "grade": {
            "score": grade.score,
            "strengths": list(grade.strengths),
            "weaknesses": list(grade.weaknesses),
            "contradictions": list(grade.contradictions),
            "reasoning": grade.reasoning,
            "ungraded_reason": grade.ungraded_reason,
            "stop_reason": grade.stop_reason,
            "raw_text": grade.raw_text,
        },
    }


# ---------------------------------------------------------------------------
# markdown
# ---------------------------------------------------------------------------


def _format(value: Number | None, kind: MetricKind) -> str:
    if value is None:
        return "n/a"
    if kind == "rate":
        return f"{value:.0%}"
    if kind == "count":
        return str(int(value))
    return f"{value:.2f}"


def _cell(metric: MetricValue, kind: MetricKind) -> str:
    if metric.value is None:
        return "n/a"
    spread = f"{_format(metric.min, kind)}–{_format(metric.max, kind)}"
    return f"{_format(metric.value, kind)} [{spread}]"


def spread_check(reference: VariantReport, other: VariantReport, metric: MetricDef) -> str:
    """Whether `other` is separated from `reference` on `metric`: their
    per-round ranges don't overlap. Needs two sample rounds on each side."""
    if reference.sample_rounds < 2 or other.sample_rounds < 2:
        return "n/a (needs 2+ sample rounds)"
    ref, cand = reference.metrics[metric.key], other.metrics[metric.key]
    if (
        ref.value is None
        or cand.value is None
        or ref.min is None
        or ref.max is None
        or cand.min is None
        or cand.max is None
    ):
        return "n/a"
    if cand.max < ref.min or cand.min > ref.max:
        direction = "lower" if cand.value < ref.value else "higher"
        return (
            f"separated: {direction} ({_format(cand.value, metric.kind)} vs "
            f"{_format(ref.value, metric.kind)})"
        )
    return "within run-to-run spread"


def _table(header: Sequence[str], rows: Sequence[Sequence[str]]) -> list[str]:
    lines = [
        "| " + " | ".join(header) + " |",
        "|" + "|".join("---" for _ in header) + "|",
    ]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return lines


def render_markdown(report: Report) -> str:
    variants = report.variants
    names = [variant.name for variant in variants]
    lines = [
        "# Persona eval report",
        "",
        f"- prompt: {report.prompt_version} · grounding: {report.grounding_version}",
        f"- narrator: {report.narrator_model} · grader: {report.grader_model} "
        f"({report.grader_prompt_version})",
        f"- samples per case: {report.samples} · cases: {len(report.cases)} · "
        f"variants: {', '.join(names)}",
        f"- calls: narrator {report.narrator_calls} + grader {report.grader_calls} = "
        f"{report.narrator_calls + report.grader_calls} of --max-calls {report.max_calls} "
        f"(worst case {report.worst_case_estimate})",
        "",
    ]
    if not report.complete:
        lines += [
            f"**PARTIAL RUN.** {report.stop_note} Every figure below covers only the "
            "narrations that finished.",
            "",
        ]
    lines += [
        "## Variants side by side",
        "",
        "Each cell is the value over every narration, then [min–max] across the sample "
        "rounds. A difference that sits inside both ranges is run-to-run noise, not a finding.",
        "",
    ]
    rows: list[list[str]] = [
        ["narrations", *(str(v.narrations) for v in variants)],
        ["served by the narrator", *(str(v.narrator_served) for v in variants)],
        ["graded", *(str(v.graded) for v in variants)],
        ["sample rounds", *(str(v.sample_rounds) for v in variants)],
    ]
    rows += [
        [metric.label, *(_cell(v.metrics[metric.key], metric.kind) for v in variants)]
        for metric in METRICS
    ]
    lines += _table(["metric", *names], rows)

    if len(variants) > 1:
        reference = variants[0]
        lines += [
            "",
            f"## Spread check against `{reference.name}`",
            "",
            "Separated means the two variants' per-round ranges don't overlap.",
            "",
        ]
        lines += _table(
            [f"metric vs {reference.name}", *names[1:]],
            [
                [metric.label, *(spread_check(reference, other, metric) for other in variants[1:])]
                for metric in METRICS
            ],
        )

    lines += ["", "## Per case"]
    for variant in variants:
        lines += ["", f"### {variant.name}", "", f"Source: `{variant.source}`", ""]
        lines += _table(
            [
                "case",
                "narrations",
                "first",
                "retry",
                "fallback",
                "untraceable",
                "claims/served",
                "mean score",
                "with contradictions",
                "ungraded",
            ],
            [
                [
                    case.case,
                    str(case.narrations),
                    str(case.first),
                    str(case.retry),
                    str(case.fallback),
                    str(case.untraceable),
                    _format(case.claims_per_narration, "mean"),
                    _format(case.mean_voice_score, "score"),
                    str(case.contradiction_narrations),
                    str(case.ungraded),
                ]
                for case in variant.per_case
            ],
        )
    return "\n".join(lines) + "\n"
