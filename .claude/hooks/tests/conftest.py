"""Make the hook scripts importable as plain modules.

The hooks run as standalone `uv run --script` files, not as a package, so the tests
put `.claude/hooks/` on `sys.path` the same way Python does when it runs a script.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

HOOKS_DIR = Path(__file__).resolve().parents[1]
CLAUDE_DIR = HOOKS_DIR.parent
REPO_ROOT = CLAUDE_DIR.parent

if str(HOOKS_DIR) not in sys.path:
    sys.path.insert(0, str(HOOKS_DIR))


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """An empty git repository, standing in for a checkout or a spoke's worktree."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "--quiet", str(repo)], check=True)
    return repo
