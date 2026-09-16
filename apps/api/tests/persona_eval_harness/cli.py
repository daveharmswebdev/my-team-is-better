"""The command line: `python -m persona_eval_harness` (package docstring).

Order matters here. This module imports only the standard library and
`persona_eval_harness.safety` at the top, parses the arguments, and runs the
refusals on the raw environment before importing anything from `api` (whose
`api.config` loads `apps/api/.env` at import) or the rest of the harness.
`tests/test_persona_eval_harness.py` checks that in a fresh interpreter.

Exit codes: 0 a complete run or a dry run; 2 refused (safety, budget, bad
arguments or an output directory that already holds a report); 3 a run the
`--max-calls` cap stopped part-way (its partial report is written).
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
    from persona_eval_harness.grader import Grader

EXIT_OK = 0
EXIT_REFUSED = 2
EXIT_PARTIAL = 3

REPORT_FILES = ("report.json", "report.md", "records.jsonl")


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
        help="hard cap on Claude calls, narrator and grader together (required for a live run)",
    )
    parser.add_argument("--out", type=Path, help="report directory (required for a live run)")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="build and print the dataset, variants and call estimate; no key, no calls",
    )
    return parser


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
    from persona_eval_harness.budget import worst_case_calls
    from persona_eval_harness.dataset import CASE_SPECS, build_dataset
    from persona_eval_harness.variants import parse_variants

    if api.config.DATABASE_URL is not None:
        return _refuse(err, "api.config resolved a DATABASE_URL; refusing to run near Postgres")

    try:
        variants = parse_variants(args.variant or ["baseline"])
    except ValueError as exc:
        return _refuse(err, str(exc))

    known = [spec.id for spec in CASE_SPECS]
    unknown = [case_id for case_id in args.case if case_id not in known]
    if unknown:
        return _refuse(err, f"unknown --case {unknown}; the case ids are {known}")
    specs = [spec for spec in CASE_SPECS if not args.case or spec.id in args.case]
    cases = build_dataset(specs)
    estimate = worst_case_calls(cases=len(cases), samples=args.samples, variants=len(variants))

    if args.dry_run:
        print(f"prompt_version {api.config.PROMPT_VERSION}", file=out)
        print(f"dataset: {len(cases)} cases", file=out)
        for case in cases:
            spec = case.spec
            digest = hashlib.sha256(case.fact_block_json.encode()).hexdigest()[:12]
            print(
                f"  {case.id}: {spec.kind} {spec.sport} {spec.year} {spec.method} "
                f"{' vs '.join(spec.teams)} contested={str(case.contested).lower()} "
                f"user_team={case.user_team} fact_block={len(case.fact_block_json)} chars "
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
            f"worst-case Claude calls: {len(cases)} cases x {args.samples} samples x "
            f"{len(variants)} variants x 3 = {estimate}",
            file=out,
        )
        if args.max_calls is not None:
            verdict = "within" if estimate <= args.max_calls else "OVER, a live run is refused"
            print(f"--max-calls {args.max_calls}: {verdict}", file=out)
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

        narrator = ClaudeNarrator()
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
    )
    for name in REPORT_FILES:
        print(out_dir / name, file=out)
    return EXIT_OK if report.complete else EXIT_PARTIAL
