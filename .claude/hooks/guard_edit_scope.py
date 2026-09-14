# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""PreToolUse hook (Edit|Write|NotebookEdit): keep a spoke inside the paths it owns.

Only subagents named in `.claude/ownership.json` are checked; the coordinator (main
thread) and built-in agents are not. Paths outside any git checkout (scratch dirs)
are always allowed. In `warn` mode the edit goes ahead with a note in the spoke's
context and a log line; in `block` mode it is denied.

Threat model: accidental scope drift. Writes through Bash are out of scope here; the
SubagentStop return check flags files_changed outside ownership instead.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ownership import Ownership, load_ownership, repo_relative


def decide(payload: dict[str, Any], ownership: Ownership) -> dict[str, Any] | None:
    agent = payload.get("agent_type")
    if not isinstance(agent, str) or agent not in ownership.agents:
        return None
    tool_input = payload.get("tool_input") or {}
    raw_path = tool_input.get("file_path") or tool_input.get("notebook_path")
    if not isinstance(raw_path, str) or not raw_path:
        return None
    target = Path(raw_path)
    if not target.is_absolute():
        target = Path(str(payload.get("cwd") or ".")) / target
    located = repo_relative(target)
    if located is None:
        return None
    root, rel = located
    entry = ownership.agents[agent]
    if entry.allows(rel):
        return None

    owns = ", ".join(entry.owns) if entry.owns else "nothing (it is read-only)"
    message = f"{agent} owns {owns}; {rel} is outside that (.claude/ownership.json)."
    if ownership.edit_scope_mode == "block":
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": (
                    f"{message} Don't work around this through another tool. If the task "
                    "really needs this file, stop and return status failure with "
                    "failure_type scope-collision, naming the file and why."
                ),
            }
        }
    _log_warning(root, agent, rel, payload)
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": (
                f"SCOPE WARNING: {message} The edit is allowed while this check is in warn "
                "mode, but it must appear in your return's files_changed, and the "
                "coordinator will see it. If you don't truly need it, revert it."
            ),
        }
    }


def _log_warning(root: Path, agent: str, rel: str, payload: dict[str, Any]) -> None:
    result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--path-format=absolute", "--git-common-dir"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return
    log = Path(result.stdout.strip()) / "claude-hooks" / "scope-warnings.jsonl"
    entry = {
        "at": datetime.now(UTC).isoformat(timespec="seconds"),
        "agent_type": agent,
        "agent_id": payload.get("agent_id"),
        "session_id": payload.get("session_id"),
        "checkout": str(root),
        "path": rel,
    }
    try:
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a") as handle:
            handle.write(json.dumps(entry) + "\n")
    except OSError:
        pass


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        output = decide(payload, load_ownership())
    except Exception as error:  # a broken guard must not stop every edit
        print(f"guard_edit_scope: {error!r}", file=sys.stderr)
        return 0
    if output is not None:
        print(json.dumps(output))
    return 0


if __name__ == "__main__":
    sys.exit(main())
