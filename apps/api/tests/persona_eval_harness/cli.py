"""The command line: `python -m persona_eval_harness` (package docstring).

Order matters here. This module imports only the standard library and
`persona_eval_harness.safety` at the top, parses the arguments, and runs the
refusals on the raw environment before importing anything from `api` (whose
`api.config` loads `apps/api/.env` at import) or the rest of the harness.
`tests/test_persona_eval_harness.py` checks that in a fresh interpreter.

`--narrator`, `--model` and `--effort` (issue #463) are checked after the
safety refusals, because the model list lives in `api.persona.claude_client`.

Exit codes: 0 a complete run with no transport error, or a dry run; 2
refused (safety, budget, bad arguments, an unknown narrator or model, an
effort the model doesn't take, a reserved variant name or an output
directory that already holds a report); 3 a run the `--max-calls` cap
stopped part-way (its partial report is written); 4 a run in which any
narrator or grader call failed with a transport error, whether or not the
cap also stopped it (the report is written, with the error counts and a
warning), so a report with outage-tainted numbers never exits like a clean
one.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, TextIO

from persona_eval_harness.safety import DEFAULT_ENV_FILE, preflight_refusals

if TYPE_CHECKING:
    from api.persona.claude_client import Narrator
    from persona_eval_harness.dataset import EvalCase
    from persona_eval_harness.grader import Grader
    from persona_eval_harness.qb_dataset import QbEvalCase
    from persona_eval_harness.variants import Variant

EXIT_OK = 0
EXIT_REFUSED = 2
EXIT_PARTIAL = 3
EXIT_TRANSPORT_ERRORS = 4

REPORT_FILES = ("report.json", "report.md", "records.jsonl")

# The served text the worst-case grader input assumes: well past the 700
# characters the persona checks allow a narration, or any fallback.
NARRATION_CHARS_BOUND = 2000


def _positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError(f"must be at least 1, got {number}")
    return number


def _non_negative_int(value: str) -> int:
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError(f"must be at least 0, got {number}")
    return number


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m persona_eval_harness",
        description=(
            "Score persona system-prompt variants side by side (issue #327). Run from apps/api "
            "with PYTHONPATH=tests, DATABASE_URL and MY_TEAM_IS_BETTER_API_ENV_FILE unset, and "
            "no apps/api/.env."
        ),
    )
    parser.add_argument(
        "--variant",
        action="append",
        default=[],
        help="baseline, degraded, or name=path/to/variant.py (repeatable; the first is the "
        "reference). Default: baseline.",
    )
    parser.add_argument(
        "--samples", type=_positive_int, default=1, help="narrations per case per variant"
    )
    parser.add_argument(
        "--case", action="append", default=[], help="restrict to this case id (repeatable)"
    )
    parser.add_argument(
        "--max-calls",
        type=_non_negative_int,
        help="hard cap on logical Claude calls, narrator and grader together (required for a "
        "live run). Each narrator submit and each grader request counts once; the SDK's "
        "automatic retries (up to 2 more HTTP requests per call) are not counted, so billed "
        "requests can reach 3x the cap",
    )
    parser.add_argument("--out", type=Path, help="report directory (required for a live run)")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="build and print the dataset, variants, call and dollar estimates; no key, no calls",
    )
    parser.add_argument(
        "--narrator",
        default="team",
        help="team (the champion, team-case and compare verdicts; default) or qb (QB vs QB)",
    )
    parser.add_argument(
        "--model",
        help="the narrator model: claude-haiku-4-5, claude-haiku-5-5 or claude-sonnet-5-5. "
        "Default: production's setting for the narrator",
    )
    parser.add_argument(
        "--effort",
        help="low, medium or high: override the effort of a 5.x model (default medium); "
        "refused with claude-haiku-4-5, which takes none",
    )
    return parser


def _worst_case_usd(
    cases: Sequence[EvalCase | QbEvalCase],
    variants: Sequence[Variant],
    *,
    samples: int,
    narrator_kind: str,
    model: str,
) -> tuple[float, float]:
    """The run's worst-case dollars, (narrator, grader): every narration
    priced by `cost.worst_case_narration_usd` on its own prompt, tool and
    fact block."""
    import json

    from api.persona.claims import tool_schema
    from api.persona.claude_client import request_profile
    from api.persona.prompt import build_user_message
    from api.persona.qb_claims import qb_tool_schema
    from api.persona.qb_prompt import build_qb_user_message
    from persona_eval_harness.cost import worst_case_narration_usd
    from persona_eval_harness.grader import GRADER_SYSTEM_PROMPT, grader_user_message
    from persona_eval_harness.qb_dataset import QbEvalCase

    tool_chars = len(json.dumps(qb_tool_schema() if narrator_kind == "qb" else tool_schema()))
    max_tokens = request_profile(model).max_tokens
    narrator_total = grader_total = 0.0
    for variant in variants:
        for case in cases:
            if isinstance(case, QbEvalCase):
                user = build_qb_user_message(case.fact_block_json)
            else:
                user = build_user_message(case.fact_block_json, contested=case.contested)
            system = variant.build_system_prompt(case.user_team)
            grader_input = GRADER_SYSTEM_PROMPT + grader_user_message(
                fact_block_json=case.fact_block_json,
                contested=case.contested,
                narration="x" * NARRATION_CHARS_BOUND,
            )
            narrator_usd, grader_usd = worst_case_narration_usd(
                narrator_model=model,
                narrator_max_tokens=max_tokens,
                narrator_input_chars=len(system) + tool_chars + len(user),
                grader_input_chars=len(grader_input),
            )
            narrator_total += samples * narrator_usd
            grader_total += samples * grader_usd
    return narrator_total, grader_total


def _refuse(err: TextIO, *reasons: str) -> int:
    for reason in reasons:
        print(f"persona_eval_harness: refused: {reason}", file=err)
    return EXIT_REFUSED


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    env_file: Path = DEFAULT_ENV_FILE,
    narrator: Narrator | None = None,
    grader: Grader | None = None,
    out: TextIO | None = None,
    err: TextIO | None = None,
) -> int:
    """Run the harness. `environ`, `env_file`, `narrator` and `grader` default
    to the real ones; the offline tests pass stand-ins."""
    out = sys.stdout if out is None else out
    err = sys.stderr if err is None else err
    args = build_parser().parse_args(argv)
    live = not args.dry_run

    refusals = preflight_refusals(
        environ=os.environ if environ is None else environ, env_file=env_file, live=live
    )
    if refusals:
        return _refuse(err, *refusals)

    # Only now: `api.config` loads apps/api/.env at import.
    import api.config
    from api.persona.claude_client import EFFORTS, PROFILES, SUPPORTED_MODELS
    from persona_eval_harness.budget import worst_case_calls
    from persona_eval_harness.dataset import CASE_SPECS, build_dataset
    from persona_eval_harness.qb_dataset import QB_CASE_SPECS, QbEvalCase, build_qb_dataset
    from persona_eval_harness.report import RunContext
    from persona_eval_harness.variants import NARRATOR_KINDS, parse_variants

    if api.config.DATABASE_URL is not None:
        return _refuse(err, "api.config resolved a DATABASE_URL; refusing to run near Postgres")

    narrator_kind = next((kind for kind in NARRATOR_KINDS if kind == args.narrator), None)
    if narrator_kind is None:
        return _refuse(err, f"unknown --narrator {args.narrator!r}; use one of {NARRATOR_KINDS}")
    model: str = args.model or (
        api.config.QB_NARRATOR_MODEL if narrator_kind == "qb" else api.config.TEAM_NARRATOR_MODEL
    )
    if model not in SUPPORTED_MODELS:
        return _refuse(err, f"unknown --model {model!r}; use one of {SUPPORTED_MODELS}")
    effort = None
    if args.effort is not None:
        effort = next((level for level in EFFORTS if level == args.effort), None)
        if effort is None:
            return _refuse(err, f"unknown --effort {args.effort!r}; use one of {EFFORTS}")
        if PROFILES[model].effort is None:
            return _refuse(err, f"--effort needs a 5.x model; {model} takes no effort setting")
    context = RunContext(narrator=narrator_kind, model=model, effort_override=effort)

    try:
        variants = parse_variants(args.variant or ["baseline"], narrator_kind)
    except ValueError as exc:
        return _refuse(err, str(exc))

    all_ids = [spec.id for spec in (QB_CASE_SPECS if narrator_kind == "qb" else CASE_SPECS)]
    unknown = [case_id for case_id in args.case if case_id not in all_ids]
    if unknown:
        return _refuse(err, f"unknown --case {unknown}; the case ids are {all_ids}")
    cases: tuple[EvalCase | QbEvalCase, ...]
    if narrator_kind == "qb":
        cases = build_qb_dataset(
            [spec for spec in QB_CASE_SPECS if not args.case or spec.id in args.case]
        )
    else:
        cases = build_dataset(
            [spec for spec in CASE_SPECS if not args.case or spec.id in args.case]
        )
    estimate = worst_case_calls(cases=len(cases), samples=args.samples, variants=len(variants))

    if args.dry_run:
        print(f"narrator {narrator_kind} · model {model} · effort {context.effort_label}", file=out)
        print(f"prompt_version {context.prompt_version}", file=out)
        print(f"dataset: {len(cases)} cases", file=out)
        for case in cases:
            digest = hashlib.sha256(case.fact_block_json.encode()).hexdigest()[:12]
            if isinstance(case, QbEvalCase):
                described = (
                    f"{case.players} career_band={case.spec.career_band} "
                    f"peak_band={case.spec.peak_band}"
                )
            else:
                spec = case.spec
                described = (
                    f"{spec.kind} {spec.sport} {spec.year} {spec.method} "
                    f"{' vs '.join(spec.teams)} contested={str(case.contested).lower()} "
                    f"user_team={case.user_team}"
                )
            print(
                f"  {case.id}: {described} fact_block={len(case.fact_block_json)} chars "
                f"sha256 {digest}",
                file=out,
            )
        print(f"variants: {len(variants)}", file=out)
        for variant in variants:
            prompt = variant.build_system_prompt(None)
            digest = hashlib.sha256(prompt.encode()).hexdigest()[:12]
            print(
                f"  {variant.name}: {variant.source} ({len(prompt)} chars, sha256 {digest})",
                file=out,
            )
        print(
            f"worst-case logical Claude calls (SDK retries not counted): {len(cases)} cases x "
            f"{args.samples} samples x {len(variants)} variants x 3 = {estimate}",
            file=out,
        )
        if args.max_calls is not None:
            verdict = "within" if estimate <= args.max_calls else "OVER, a live run is refused"
            print(f"--max-calls {args.max_calls}: {verdict}", file=out)
        narrator_usd, grader_usd = _worst_case_usd(
            cases, variants, samples=args.samples, narrator_kind=narrator_kind, model=model
        )
        print(
            f"worst-case dollars (every call spends max_tokens; see cost.py): narrator "
            f"${narrator_usd:.2f} on {model} + grader ${grader_usd:.2f} = "
            f"${narrator_usd + grader_usd:.2f}",
            file=out,
        )
        print("dry run: no Claude calls made", file=out)
        return EXIT_OK

    if args.max_calls is None or args.out is None:
        return _refuse(err, "a live run needs --max-calls and --out")
    if estimate > args.max_calls:
        return _refuse(
            err,
            f"the worst case is {estimate} Claude calls ({len(cases)} cases x {args.samples} "
            f"samples x {len(variants)} variants x 3), over --max-calls {args.max_calls}",
        )
    out_dir: Path = args.out
    existing = [name for name in REPORT_FILES if (out_dir / name).exists()]
    if existing:
        return _refuse(err, f"{out_dir} already holds {existing}; pick a new --out")

    from persona_eval_harness.runner import run_to_directory

    if narrator is None:
        from api.persona.claude_client import ClaudeNarrator
        from api.persona.qb_claims import qb_tool_schema

        narrator = ClaudeNarrator(
            model=model,
            tool=qb_tool_schema() if narrator_kind == "qb" else None,
            effort=effort,
        )
    if grader is None:
        from persona_eval_harness.grader import ModelGrader

        grader = ModelGrader()

    report = run_to_directory(
        cases=cases,
        variants=variants,
        samples=args.samples,
        narrator=narrator,
        grader=grader,
        max_calls=args.max_calls,
        worst_case_estimate=estimate,
        out_dir=out_dir,
        progress=err,
        context=context,
    )
    for name in REPORT_FILES:
        print(out_dir / name, file=out)
    if report.narrator_errors or report.grader_errors:
        return EXIT_TRANSPORT_ERRORS
    return EXIT_OK if report.complete else EXIT_PARTIAL
