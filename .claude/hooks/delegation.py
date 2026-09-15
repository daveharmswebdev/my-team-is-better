# /// script
# requires-python = ">=3.12"
# dependencies = ["jsonschema==4.26.0"]
# ///
"""The delegation contract, checked by code.

    uv run --script .claude/hooks/delegation.py render-brief <brief.json>
    uv run --script .claude/hooks/delegation.py validate-brief <brief.json>
    uv run --script .claude/hooks/delegation.py validate-return --agent <name> <file>
    uv run --script .claude/hooks/delegation.py subagent-stop    (SubagentStop hook, stdin)

`render-brief` validates a brief against brief.schema.json and the ownership map, then
prints the prompt to hand to the Agent tool. The SubagentStop hook validates a spoke's
final message against return.schema.json plus the rules a schema can't express. If it
doesn't validate, the spoke is asked to fix it, with the errors as feedback, up to
MAX_RETURN_RETRIES times.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, ValidationError

from ownership import CLAUDE_DIR, Ownership, load_ownership, scope_within

__all__ = [
    "MAX_RETURN_RETRIES",
    "ReturnCheck",
    "extract_json_block",
    "load_ownership",
    "render_brief",
    "subagent_stop",
    "validate_brief",
    "validate_return",
]

MAX_RETURN_RETRIES = 2
SCHEMAS_DIR = CLAUDE_DIR / "schemas"

_FENCE = re.compile(r"```json[ \t]*\n(.*?)\n[ \t]*```", re.DOTALL)


@dataclass(frozen=True)
class ReturnCheck:
    errors: list[str]
    warnings: list[str] = field(default_factory=list)


def _schema(name: str) -> dict[str, Any]:
    schema: dict[str, Any] = json.loads((SCHEMAS_DIR / name).read_text())
    return schema


def _where(error: ValidationError) -> str:
    return "/".join(str(part) for part in error.absolute_path) or "(root)"


def _describe(error: ValidationError) -> list[str]:
    """Readable messages; for oneOf, the errors of the branch the data was aiming at."""
    if error.validator == "oneOf" and error.context:
        branches: dict[int, list[ValidationError]] = defaultdict(list)
        for sub in error.context:
            branches[int(sub.relative_schema_path[0])].append(sub)
        aimed = [
            subs
            for subs in branches.values()
            if not any(s.validator in ("const", "type") and len(s.relative_path) <= 1 for s in subs)
        ]
        if len(aimed) == 1:
            return [message for sub in aimed[0] for message in _describe(sub)]
    return [f"{_where(error)}: {error.message}"]


def _schema_errors(data: object, schema: dict[str, Any]) -> list[str]:
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(data), key=lambda e: [str(p) for p in e.absolute_path])
    return [message for error in errors for message in _describe(error)]


def extract_json_block(message: str) -> tuple[object | None, list[str]]:
    matches = list(_FENCE.finditer(message))
    if not matches:
        return None, [
            "no fenced ```json block found: the final message must be exactly one "
            "fenced ```json block"
        ]
    if len(matches) > 1:
        return None, [
            f"found {len(matches)} fenced ```json blocks: the final message must contain "
            "exactly one"
        ]
    match = matches[0]
    outside = (message[: match.start()] + message[match.end() :]).strip()
    if outside:
        snippet = outside if len(outside) <= 80 else outside[:77] + "..."
        return None, [
            f"text outside the fence ({snippet!r}): put nothing outside the ```json block"
        ]
    try:
        return json.loads(match.group(1)), []
    except json.JSONDecodeError as error:
        return None, [f"the fenced block is not valid JSON: {error}"]


def validate_return(data: object, *, agent_type: str | None, ownership: Ownership) -> ReturnCheck:
    errors = _schema_errors(data, _schema("return.schema.json"))
    if errors or not isinstance(data, dict):
        return ReturnCheck(errors)

    warnings: list[str] = []
    agent = data["agent"]
    if agent_type is not None and agent != agent_type:
        errors.append(f"agent: the return says {agent!r} but it came from {agent_type!r}")
    known_owners = set(ownership.agents) | {"coordinator"}
    for index, finding in enumerate(data["findings"]):
        if finding["owner"] not in known_owners:
            errors.append(
                f"findings/{index}/owner: {finding['owner']!r} is not an agent in "
                ".claude/ownership.json or 'coordinator'"
            )

    name = agent_type or agent
    entry = ownership.agents.get(name)
    if entry is None:
        return ReturnCheck(errors, warnings)
    read_only = entry.kind == "read-only"
    files_changed = data.get("files_changed", [])

    if read_only and files_changed:
        errors.append(f"files_changed: {name} is read-only and must not change files")
    if not read_only:
        for change in files_changed:
            if not entry.allows(change["path"]):
                warnings.append(
                    f"{change['path']} is outside {name}'s ownership ({', '.join(entry.owns)})"
                )

    if data["status"] == "success":
        runs = data["tests_run"]
        for index, run in enumerate(runs):
            expected_red = run["phase"] in ("red", "sabotage")
            if not read_only and run["result"] in ("fail", "error") and not expected_red:
                errors.append(
                    f"tests_run/{index}: result {run['result']!r} in phase {run['phase']!r}. "
                    "On success only a red or sabotage run may fail: fix it, or return status "
                    "failure with failure_type rubric-failed"
                )
        if read_only:
            if not runs:
                errors.append(
                    "tests_run: a read-only agent's success must list the checks it ran; an "
                    "empty list can't be told apart from a run that never happened"
                )
        else:
            if not any(r["result"] == "pass" and r["phase"] in ("green", "gate") for r in runs):
                errors.append(
                    "tests_run: implementation success needs at least one passing green or gate run"
                )
            if not files_changed:
                errors.append(
                    "files_changed: implementation success with no changed files is an empty "
                    "deliverable"
                )
            for index, finding in enumerate(data["findings"]):
                if finding["severity"] == "blocking" and finding["owner"] == agent:
                    errors.append(
                        f"findings/{index}: a blocking finding you own means the work isn't "
                        "done; return status failure with failure_type rubric-failed instead"
                    )
    return ReturnCheck(errors, warnings)


def validate_brief(data: object, ownership: Ownership) -> list[str]:
    errors = _schema_errors(data, _schema("brief.schema.json"))
    if errors or not isinstance(data, dict):
        return errors
    agent = data["agent"]
    entry = ownership.agents.get(agent)
    if entry is None:
        known = ", ".join(sorted(ownership.agents))
        return [f"agent: {agent!r} is not in .claude/ownership.json ({known})"]
    if entry.kind == "implementation":
        for index, scope in enumerate(data["scope"]):
            if not scope_within(scope, entry.owns):
                errors.append(
                    f"scope/{index}: {scope!r} is outside {agent}'s ownership "
                    f"({', '.join(entry.owns)}). Split the round, or route that part to its owner"
                )
    if Path(data["scratch_dir"].rstrip("/")).name == "scratchpad":
        errors.append(
            "scratch_dir: give this spoke its own subdirectory (e.g. "
            "<scratchpad>/<issue>-<agent>-r<round>/), never the shared scratchpad root"
        )
    return errors


def _is_read_only(agent: str, ownership: Ownership | None) -> bool:
    entry = ownership.agents.get(agent) if ownership is not None else None
    return entry is not None and entry.kind == "read-only"


def _base_section(sha: str, *, read_only: bool) -> str:
    if read_only:
        return (
            f"## BASE\nReview against `{sha}`; do not change HEAD. Your checkout is expected "
            f"to be at or after this commit (a review covers the range after it). If "
            f"`git merge-base --is-ancestor {sha} HEAD` fails, stop and return status failure "
            "with failure_type blocked-by-missing-input. Report this commit as base_sha."
        )
    return (
        f"## BASE\nStart from commit `{sha}`. Before changing anything, run "
        f"`git rev-parse HEAD`. If it differs, run `git merge --ff-only {sha}`. If that "
        "isn't a fast-forward, stop and return status failure with failure_type "
        "blocked-by-missing-input. Report this commit as base_sha."
    )


def _bullets(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items)


def render_brief(brief: dict[str, Any], ownership: Ownership | None = None) -> str:
    """The prompt for the Agent tool. Assumes `validate_brief` returned no errors.

    `ownership` decides the BASE wording: a read-only spoke (reviewer, validator)
    reviews a range *after* `base_sha`, so its HEAD is always ahead of it and the
    fast-forward instruction can't apply (#239). Without `ownership`, every agent
    gets the implementation wording.
    """
    who = brief["agent"]
    if brief.get("round"):
        who += f", round {brief['round']}"
    if brief["issue"] is not None:
        who += f", issue #{brief['issue']}"
    contract = brief["contract"] if brief["contract"] is not None else "None needed for this task."
    sha = brief["base_sha"]
    sections = [
        f"Brief for {who}.",
        f"## OBJECTIVE\n{brief['objective']}",
        f"## CONTRACT\n{contract}",
        "## SCOPE\nYou may change only:\n" + _bullets([f"`{s}`" for s in brief["scope"]]),
        "## NEGATIVE\n" + _bullets(brief["negative"]),
        "## RUBRIC\n" + _bullets(brief["rubric"]),
        _base_section(sha, read_only=_is_read_only(brief["agent"], ownership)),
        (
            f"## SCRATCH\nYour own scratch directory is `{brief['scratch_dir']}`. Create it, "
            "and put every temporary file there (runners, sabotage scripts, dbs, logs) and "
            "nowhere else. Other spokes may be running at the same time."
        ),
        f"## CONCURRENCY\n{brief['concurrency'] or 'Nothing else is running.'}",
    ]
    gate = brief["gate"]
    if gate is not None:
        out_of_scope = _bullets(gate["out_of_scope"]) if gate["out_of_scope"] else "- (none)"
        sections.append(
            "## GATE\n"
            f"Threat model: {gate['threat_model']}\n"
            f"Blocking means: {gate['blocking_definition']}\n"
            "Out of scope (report as pre-existing findings for their own issues, never as "
            f"blocking):\n{out_of_scope}\n"
            f"Review stops after round {gate['max_review_rounds']}."
        )
    sections.append(
        "---\nFinish with exactly one fenced ```json block conforming to "
        "`.claude/schemas/return.schema.json`, with nothing outside it; your preloaded "
        "spoke-protocol skill has the rules. A hook validates it when you stop and tells you "
        "what to fix."
    )
    return "\n\n".join(sections) + "\n"


def _state_file(state_dir: Path, agent_id: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", agent_id)
    return state_dir / f"{safe}.return-attempts"


def subagent_stop(
    payload: dict[str, Any], ownership: Ownership, state_dir: Path
) -> dict[str, Any] | None:
    agent = payload.get("agent_type")
    if not isinstance(agent, str) or agent not in ownership.agents:
        return None
    message = payload.get("last_assistant_message")
    data, errors = extract_json_block(message if isinstance(message, str) else "")
    warnings: list[str] = []
    if not errors:
        check = validate_return(data, agent_type=agent, ownership=ownership)
        errors, warnings = check.errors, check.warnings

    agent_id = str(payload.get("agent_id") or agent)
    if errors:
        state_dir.mkdir(parents=True, exist_ok=True)
        counter = _state_file(state_dir, agent_id)
        attempts = int(counter.read_text()) + 1 if counter.exists() else 1
        counter.write_text(str(attempts))
        if attempts <= MAX_RETURN_RETRIES:
            return {
                "decision": "block",
                "reason": (
                    "Your return does not validate against .claude/schemas/return.schema.json "
                    f"(retry {attempts} of {MAX_RETURN_RETRIES}). Don't redo the work. Fix "
                    "exactly these problems and send the whole return again as one fenced "
                    "```json block with nothing outside it:\n" + _bullets(errors)
                ),
            }
        return {
            "systemMessage": (
                f"{agent} ({agent_id}): the return is still invalid after "
                f"{MAX_RETURN_RETRIES} retries. Record this round as failure_type "
                "malformed-return. Last errors: " + "; ".join(errors)
            )
        }

    assert isinstance(data, dict)
    note = (
        f"{agent} ({agent_id}) return validated against return.schema.json v2: "
        f"status {data['status']}."
    )
    if warnings:
        note += " Scope warnings: " + "; ".join(warnings)
    return {"systemMessage": note}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("render-brief", "validate-brief"):
        commands.add_parser(name).add_argument("brief")
    validate = commands.add_parser("validate-return")
    validate.add_argument("--agent", required=True)
    validate.add_argument("path", help="a .json return, or a message with one ```json block")
    commands.add_parser("subagent-stop")
    args = parser.parse_args(argv)

    if args.command == "subagent-stop":
        try:
            payload = json.load(sys.stdin)
            scratch = payload.get("scratchpad_dir")
            base = Path(scratch) if isinstance(scratch, str) else Path(tempfile.gettempdir())
            output = subagent_stop(payload, load_ownership(), base / "claude-delegation-hook")
        except Exception as error:  # a broken hook must not trap a spoke
            print(f"delegation subagent-stop: {error!r}", file=sys.stderr)
            return 0
        if output is not None:
            print(json.dumps(output))
        return 0

    ownership = load_ownership()
    if args.command in ("render-brief", "validate-brief"):
        brief = json.loads(Path(args.brief).read_text())
        brief_errors = validate_brief(brief, ownership)
        if brief_errors:
            print("\n".join(brief_errors), file=sys.stderr)
            return 1
        print(render_brief(brief, ownership) if args.command == "render-brief" else "brief ok")
        return 0

    text = sys.stdin.read() if args.path == "-" else Path(args.path).read_text()
    errors: list[str] = []
    if text.lstrip().startswith("{"):
        data: object = json.loads(text)
    else:
        data, errors = extract_json_block(text)
    if errors:
        check = ReturnCheck(errors)
    else:
        check = validate_return(data, agent_type=args.agent, ownership=ownership)
    for warning in check.warnings:
        print(f"warning: {warning}", file=sys.stderr)
    if check.errors:
        print("\n".join(check.errors), file=sys.stderr)
        return 1
    print("return ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
