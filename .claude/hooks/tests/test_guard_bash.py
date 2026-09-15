"""PreToolUse guard for Bash: the two git mistakes that hurt every concurrent session.

1. Pushing to `main`. GitHub's ruleset rejects it too (CLAUDE.md); the hook stops it
   before the push leaves the session, with a message that says why.
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
        ("git push --repo=origin main", "feat/x"),
        ("git stash", "feat/x"),
        ("git stash pop", "feat/x"),
        ("git stash push -u", "feat/x"),
        ("git stash drop", "feat/x"),
        ("npm test; git stash pop", "feat/x"),
        ("npm test\ngit stash pop", "feat/x"),
        # Found by the round-1 review: keywords and wrappers in front of git.
        ("if true; then git stash pop; fi", "feat/x"),
        ("for b in x; do git push origin main; done", "feat/x"),
        ("timeout 60 git push origin main", "feat/x"),
        ("nohup git push origin main", "feat/x"),
        # An apostrophe inside a heredoc body used to switch every check off.
        ("cat > /tmp/n.md <<'EOF'\nIt's done\nEOF\ngit push origin main", "feat/x"),
        # Found by the round-2 review: line continuations and trailing comments.
        ("git push \\\n  origin main", "feat/x"),
        ("git push -u origin \\\n  main", "feat/x"),
        ("uv run pytest -q \\\n  tests && git push origin \\\n  main", "feat/x"),
        ("git push origin main  # don't forget the PR", "feat/x"),
        ("git stash pop  # it's mine", "feat/x"),
        ("git push  # push it's branch", "main"),
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
        ("gh pr merge 191 --squash --delete-branch", "feat/x"),
        ("gh pr create --draft --base main --title 'x'", "feat/x"),
        ("git log --oneline main", "main"),
        ("git fetch origin main", "main"),
        ("git rebase --onto origin/main 1a2b3c4 feat/x", "feat/x"),
        ("git worktree add ../wt -b feat/y origin/main", "main"),
        ("git merge --ff-only bf8b9de", "feat/x"),
        # Found by the round-1 review: the branch changes earlier in the same command.
        ("git switch -c feat/new && git push -u origin HEAD", "main"),
        ("git checkout -b feat/new && git push -u origin HEAD", "main"),
        # Text that only mentions the forbidden commands: commit messages and heredocs.
        ("git commit -F - <<'EOF'\nDon't git push origin main\ngit stash pop\nEOF", "feat/x"),
        ('git commit -m "Subject\n\ngit stash pop is dangerous"', "feat/x"),
        # Found by the round-2 review: line continuations and trailing comments.
        ("git push \\\n  origin feat/x", "main"),
        ("git push -u \\\n  origin feat/x", "main"),
        ("git stash push \\\n  -u -m 'tag'", "feat/x"),
        ("git push origin feat/x # not main", "feat/x"),
        ("git push -u origin feat/x  # then open a PR into main", "feat/x"),
        ("git push origin issue#12-fix", "feat/x"),
        ('git commit -m "Subject\n\nfixes #12, not main"', "feat/x"),
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
