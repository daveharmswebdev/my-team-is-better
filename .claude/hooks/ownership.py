# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Load `.claude/ownership.json` and answer "may this agent edit this path?".

Shared by the edit-scope hook and the delegation checks, so the ownership map lives
in one file instead of being restated in prose in each agent definition.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path

CLAUDE_DIR = Path(__file__).resolve().parents[1]
OWNERSHIP_PATH = CLAUDE_DIR / "ownership.json"

AGENT_KINDS = frozenset({"implementation", "read-only"})
EDIT_SCOPE_MODES = frozenset({"warn", "block"})
_WILDCARD_CHARS = frozenset("*?[")


def path_matches(rel_path: str, pattern: str) -> bool:
    """Match a repo-relative path against a glob where `**` spans whole segments."""
    return _match_segments(rel_path.strip("/").split("/"), pattern.strip("/").split("/"))


def _match_segments(parts: list[str], patterns: list[str]) -> bool:
    if not patterns:
        return not parts
    head, rest = patterns[0], patterns[1:]
    if head == "**":
        return any(_match_segments(parts[i:], rest) for i in range(len(parts) + 1))
    return bool(parts) and fnmatchcase(parts[0], head) and _match_segments(parts[1:], rest)


def _has_wildcard(segment: str) -> bool:
    return any(char in _WILDCARD_CHARS for char in segment)


def scope_within(scope: str, owns: list[str] | tuple[str, ...]) -> bool:
    """True if every path a brief's scope glob could name is inside an owned pattern."""
    parts = scope.strip("/").split("/")
    if not any(_has_wildcard(part) for part in parts):
        return any(path_matches(scope, pattern) for pattern in owns)
    static: list[str] = []
    for part in parts:
        if _has_wildcard(part):
            break
        static.append(part)
    for pattern in owns:
        owned = pattern.strip("/").split("/")
        if owned[-1] != "**" or any(_has_wildcard(part) for part in owned[:-1]):
            continue
        prefix = owned[:-1]
        if static[: len(prefix)] == prefix:
            return True
    return False


@dataclass(frozen=True)
class AgentEntry:
    kind: str
    owns: tuple[str, ...]

    def allows(self, rel_path: str) -> bool:
        return any(path_matches(rel_path, pattern) for pattern in self.owns)


@dataclass(frozen=True)
class Ownership:
    agents: dict[str, AgentEntry]
    edit_scope_mode: str


def load_ownership(path: Path = OWNERSHIP_PATH) -> Ownership:
    raw = json.loads(path.read_text())
    mode = raw["edit_scope_mode"]
    if mode not in EDIT_SCOPE_MODES:
        raise ValueError(
            f"{path}: edit_scope_mode must be one of {sorted(EDIT_SCOPE_MODES)}, not {mode!r}"
        )
    agents: dict[str, AgentEntry] = {}
    for name, entry in raw["agents"].items():
        if entry["kind"] not in AGENT_KINDS:
            raise ValueError(f"{path}: {name}.kind must be one of {sorted(AGENT_KINDS)}")
        agents[name] = AgentEntry(kind=entry["kind"], owns=tuple(entry["owns"]))
    return Ownership(agents=agents, edit_scope_mode=mode)


def git_toplevel(path: Path) -> Path | None:
    """The checkout (main or worktree) containing `path`, which may not exist yet."""
    probe = path
    while not probe.exists():
        if probe.parent == probe:
            return None
        probe = probe.parent
    if not probe.is_dir():
        probe = probe.parent
    result = subprocess.run(
        ["git", "-C", str(probe), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    return Path(result.stdout.strip())


def repo_relative(path: Path) -> tuple[Path, str] | None:
    """(checkout root, repo-relative posix path), or None outside any git checkout."""
    top = git_toplevel(path)
    if top is None:
        return None
    try:
        rel = path.resolve().relative_to(top.resolve())
    except ValueError:
        return None
    return top, rel.as_posix()
