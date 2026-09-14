"""PreToolUse guard: a spoke's Edit/Write must land inside the paths it owns.

Threat model: this stops accidental scope drift (a spoke "helpfully" fixing a file in
another spoke's module). It does not try to stop deliberate evasion -- a spoke can
still write through Bash, and the SubagentStop return check reports that separately.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from guard_edit_scope import decide
from ownership import AgentEntry, Ownership


def _ownership(mode: str) -> Ownership:
    return Ownership(
        agents={
            "api-agent": AgentEntry(kind="implementation", owns=("apps/api/**",)),
            "reviewer": AgentEntry(kind="read-only", owns=()),
        },
        edit_scope_mode=mode,
    )


def _payload(
    file_path: str, cwd: Path, agent_type: str | None, tool: str = "Edit"
) -> dict[str, Any]:
    key = "notebook_path" if tool == "NotebookEdit" else "file_path"
    payload: dict[str, Any] = {
        "hook_event_name": "PreToolUse",
        "tool_name": tool,
        "tool_input": {key: file_path},
        "cwd": str(cwd),
    }
    if agent_type is not None:
        payload["agent_id"] = "agent_1"
        payload["agent_type"] = agent_type
    return payload


def test_main_thread_is_never_checked(git_repo: Path) -> None:
    payload = _payload(str(git_repo / "apps/web/src/App.tsx"), git_repo, agent_type=None)
    assert decide(payload, _ownership("block")) is None


def test_owned_path_is_allowed_even_before_its_directory_exists(git_repo: Path) -> None:
    payload = _payload(str(git_repo / "apps/api/src/api/new_module.py"), git_repo, "api-agent")
    assert decide(payload, _ownership("block")) is None


def test_unowned_path_is_denied_in_block_mode(git_repo: Path) -> None:
    payload = _payload(str(git_repo / "apps/web/src/App.tsx"), git_repo, "api-agent")
    output = decide(payload, _ownership("block"))
    assert output is not None
    specific = output["hookSpecificOutput"]
    assert specific["permissionDecision"] == "deny"
    assert "apps/web/src/App.tsx" in specific["permissionDecisionReason"]
    assert "apps/api/**" in specific["permissionDecisionReason"]
    assert "scope-collision" in specific["permissionDecisionReason"]


def test_unowned_path_only_warns_in_warn_mode(git_repo: Path) -> None:
    payload = _payload(str(git_repo / "apps/web/src/App.tsx"), git_repo, "api-agent")
    output = decide(payload, _ownership("warn"))
    assert output is not None
    specific = output["hookSpecificOutput"]
    assert "permissionDecision" not in specific
    assert "apps/web/src/App.tsx" in specific["additionalContext"]


def test_warn_mode_leaves_a_log_line_shared_by_every_worktree(git_repo: Path) -> None:
    payload = _payload(str(git_repo / "apps/web/src/App.tsx"), git_repo, "api-agent")
    decide(payload, _ownership("warn"))
    common_dir = subprocess.run(
        ["git", "-C", str(git_repo), "rev-parse", "--path-format=absolute", "--git-common-dir"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    log = Path(common_dir) / "claude-hooks" / "scope-warnings.jsonl"
    entry = json.loads(log.read_text().splitlines()[-1])
    assert entry["agent_type"] == "api-agent"
    assert entry["path"] == "apps/web/src/App.tsx"


def test_relative_path_resolves_against_the_hook_cwd(git_repo: Path) -> None:
    payload = _payload("apps/web/src/App.tsx", git_repo, "api-agent")
    output = decide(payload, _ownership("block"))
    assert output is not None
    assert output["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_path_outside_any_repository_is_allowed(tmp_path: Path, git_repo: Path) -> None:
    scratch = tmp_path / "scratchpad" / "api-181" / "notes.md"
    assert decide(_payload(str(scratch), git_repo, "api-agent"), _ownership("block")) is None


def test_agents_outside_the_map_are_not_checked(git_repo: Path) -> None:
    payload = _payload(str(git_repo / "apps/web/src/App.tsx"), git_repo, "general-purpose")
    assert decide(payload, _ownership("block")) is None


def test_read_only_agent_may_not_write_inside_the_repo(git_repo: Path) -> None:
    payload = _payload(str(git_repo / "apps/api/src/api/main.py"), git_repo, "reviewer")
    output = decide(payload, _ownership("block"))
    assert output is not None
    assert output["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_notebook_edit_uses_notebook_path(git_repo: Path) -> None:
    payload = _payload(
        str(git_repo / "apps/web/x.ipynb"), git_repo, "api-agent", tool="NotebookEdit"
    )
    output = decide(payload, _ownership("block"))
    assert output is not None
    assert output["hookSpecificOutput"]["permissionDecision"] == "deny"
