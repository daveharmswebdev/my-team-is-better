"""PreToolUse guard for Bash: the two git mistakes that hurt every concurrent session.

1. Pushing to `main`. Branch protection can't be enforced by GitHub on this private
   repo (CLAUDE.md), so the rule was prose only.
2. Popping the shared stash. The stash stack is shared by every worktree, so a bare
   `git stash` / `git stash pop` can take another session's changes.

Threat model: accidental commands. A command built at runtime (`eval`, variables) is
out of scope.
"""

from __future__ import annotations

import pytest

from guard_bash import check_command


@pytest.mark.parametrize(
    ("command", "branch"),
    [
        ("git push origin main", "feat/x"),
        ("git push origin HEAD:main", "feat/x"),
        ("git push -f origin feat/x:refs/heads/main", "feat/x"),
        ("git push --force origin +main", "feat/x"),
        ("cd apps/web && git push origin main", "feat/x"),
        ("git -C ../other push origin main", "feat/x"),
        ("git push", "main"),
        ("git push origin", "main"),
        ("git push -u origin HEAD", "main"),
        ("git stash", "feat/x"),
        ("git stash pop", "feat/x"),
        ("git stash push -u", "feat/x"),
        ("git stash drop", "feat/x"),
        ("npm test; git stash pop", "feat/x"),
    ],
)
def test_blocked(command: str, branch: str) -> None:
    assert check_command(command, current_branch=branch) is not None


@pytest.mark.parametrize(
    ("command", "branch"),
    [
        ("git push -u origin claude-optimization", "claude-optimization"),
        ("git push origin feat/main-menu", "feat/main-menu"),
        ("git push", "feat/x"),
        ("git push --force-with-lease origin feat/x", "feat/x"),
        ("git stash list", "feat/x"),
        ("git stash push -u -m 'wip-claude-optimization'", "feat/x"),
        ("git stash apply 3f2e1d0", "feat/x"),
        ("git stash drop stash@{2}", "feat/x"),
        ("echo 'git push origin main'", "feat/x"),
        ("gh pr merge 190 --squash", "feat/x"),
        ("git log --oneline main", "main"),
        ("git fetch origin main", "main"),
    ],
)
def test_allowed(command: str, branch: str) -> None:
    assert check_command(command, current_branch=branch) is None


def test_reason_names_the_safe_alternative() -> None:
    reason = check_command("git stash pop", current_branch="feat/x")
    assert reason is not None
    assert "git stash apply" in reason
    push_reason = check_command("git push origin main", current_branch="feat/x")
    assert push_reason is not None
    assert "pull request" in push_reason
