"""`.claude/settings.json` wires the hooks; these tests keep that wiring honest."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

CLAUDE_DIR = Path(__file__).resolve().parents[2]


def _settings() -> dict[str, Any]:
    settings: dict[str, Any] = json.loads((CLAUDE_DIR / "settings.json").read_text())
    return settings


def _hook_commands() -> list[str]:
    return [
        hook["command"]
        for groups in _settings()["hooks"].values()
        for group in groups
        for hook in group["hooks"]
    ]


def test_every_hook_command_runs_a_script_that_exists() -> None:
    commands = _hook_commands()
    assert len(commands) == 3
    for command in commands:
        scripts = re.findall(r"\.claude/hooks/([\w.-]+\.py)", command)
        assert scripts, command
        for script in scripts:
            assert (CLAUDE_DIR / "hooks" / script).is_file(), script


def test_a_missing_hook_script_is_skipped_rather_than_failing_closed() -> None:
    # uv exits 2 on a missing script, and exit 2 from PreToolUse blocks every tool call,
    # including the git command that would restore the script.
    for command in _hook_commands():
        assert '[ -f "$f" ] || exit 0' in command, command


def test_worktree_spokes_branch_from_the_coordinators_head() -> None:
    assert _settings()["worktree"]["baseRef"] == "head"
