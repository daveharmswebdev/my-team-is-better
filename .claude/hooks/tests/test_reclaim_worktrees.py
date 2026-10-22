"""`reclaim_worktrees.py` removes spoke worktrees and branches whose work is in main (#339).

Every test builds its own throwaway repository: a primary checkout with spoke worktrees
under `.claude/worktrees/agent-*`, and `refs/remotes/origin/main` set by hand to stand in
for the remote. Work lands on main as a squash commit, as `/ship` does it.
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import pytest

import reclaim_worktrees as rw

LATER = time.time() + 48 * 3600  # old enough for every default age check


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def commit_file(repo: Path, name: str, text: str, message: str) -> str:
    (repo / name).write_text(text)
    git(repo, "add", name)
    git(repo, "commit", "--quiet", "-m", message)
    return git(repo, "rev-parse", "HEAD")


def publish_main(repo: Path) -> None:
    git(repo, "update-ref", "refs/remotes/origin/main", git(repo, "rev-parse", "main"))


@pytest.fixture
def repo(git_repo: Path) -> Path:
    git(git_repo, "config", "user.email", "t@example.com")
    git(git_repo, "config", "user.name", "t")
    git(git_repo, "checkout", "--quiet", "-b", "main")
    commit_file(git_repo, "README", "base\n", "base")
    publish_main(git_repo)
    return git_repo


def add_spoke(repo: Path, name: str, branch: str | None = None) -> Path:
    path = repo / ".claude" / "worktrees" / name
    branch = branch or f"worktree-{name}"
    git(repo, "worktree", "add", "--quiet", "-b", branch, str(path), "main")
    return path


def squash_onto_main(repo: Path, name: str, text: str) -> None:
    """Land the same change on main as a new commit, the way a squash merge does."""
    commit_file(repo, name, text, f"squash {name}")
    publish_main(repo)


def by_name(entries: list[rw.Entry]) -> dict[str, rw.Entry]:
    return {e.name: e for e in entries}


def test_squash_merged_spoke_is_a_candidate(repo: Path) -> None:
    wt = add_spoke(repo, "agent-a")
    commit_file(wt, "a.txt", "a\n", "spoke a")
    squash_onto_main(repo, "a.txt", "a\n")

    entry = by_name(rw.survey(repo, now=LATER))["agent-a"]
    assert entry.reason is None
    assert entry.kind == "worktree"


def test_unmerged_work_is_kept(repo: Path) -> None:
    wt = add_spoke(repo, "agent-b")
    commit_file(wt, "b.txt", "b\n", "spoke b")

    assert by_name(rw.survey(repo, now=LATER))["agent-b"].reason == rw.NOT_IN_MAIN


def test_partly_merged_work_is_kept(repo: Path) -> None:
    wt = add_spoke(repo, "agent-p")
    commit_file(wt, "p.txt", "p\n", "spoke p")
    commit_file(wt, "q.txt", "q\n", "spoke p, second file")
    squash_onto_main(repo, "p.txt", "p\n")

    assert by_name(rw.survey(repo, now=LATER))["agent-p"].reason == rw.NOT_IN_MAIN


def test_work_main_later_changed_is_kept(repo: Path) -> None:
    # Main reworked the same line after the spoke wrote it; merging conflicts, so
    # the spoke's version may be the only copy of something.
    wt = add_spoke(repo, "agent-r")
    commit_file(wt, "README", "spoke's version\n", "spoke r")
    squash_onto_main(repo, "README", "main's version\n")

    assert by_name(rw.survey(repo, now=LATER))["agent-r"].reason == rw.NOT_IN_MAIN


def test_dirty_worktree_is_kept_even_when_merged(repo: Path) -> None:
    wt = add_spoke(repo, "agent-c")
    (wt / "scratch.txt").write_text("unreturned work\n")

    assert by_name(rw.survey(repo, now=LATER))["agent-c"].reason == rw.DIRTY


def test_recent_worktree_is_kept(repo: Path) -> None:
    # A spoke that has just started sits clean at its base, which main contains;
    # only its age protects it.
    add_spoke(repo, "agent-d")

    assert by_name(rw.survey(repo))["agent-d"].reason == rw.RECENT


def test_age_ignores_git_housekeeping_mtimes(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Found on the real repo: `git status` rewrites a worktree's index and gc rewrites
    # reflog files, so their mtimes said every parked spoke was "recent".
    monkeypatch.setenv("GIT_COMMITTER_DATE", "@1700000000 +0000")
    wt = add_spoke(repo, "agent-old")
    commit_file(wt, "o.txt", "o\n", "spoke old")
    squash_onto_main(repo, "o.txt", "o\n")
    os.utime(wt, (1700000000, 1700000000))
    common = Path(git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir"))
    for housekeeping in (common / "worktrees" / "agent-old" / "index", common / "logs"):
        os.utime(housekeeping)  # now

    assert by_name(rw.survey(repo))["agent-old"].reason is None


def test_locked_worktree_is_kept(repo: Path) -> None:
    wt = add_spoke(repo, "agent-l")
    git(repo, "worktree", "lock", str(wt))

    assert by_name(rw.survey(repo, now=LATER))["agent-l"].reason == rw.LOCKED


def test_non_agent_worktrees_and_branches_are_ignored(repo: Path) -> None:
    add_spoke(repo, "issue-349", branch="issue-349-x")
    git(repo, "branch", "feature-old")

    names = set(by_name(rw.survey(repo, now=LATER)))
    assert names.isdisjoint({"issue-349", "issue-349-x", "feature-old", "main"})


def test_orphan_branches(repo: Path) -> None:
    wt = add_spoke(repo, "agent-e")
    commit_file(wt, "e.txt", "e\n", "spoke e")
    squash_onto_main(repo, "e.txt", "e\n")
    wt2 = add_spoke(repo, "agent-f")
    commit_file(wt2, "f.txt", "f\n", "spoke f")
    for path in (wt, wt2):
        git(repo, "worktree", "remove", str(path))

    entries = by_name(rw.survey(repo, now=LATER))
    assert entries["worktree-agent-e"].kind == "branch"
    assert entries["worktree-agent-e"].reason is None
    assert entries["worktree-agent-f"].reason == rw.NOT_IN_MAIN


def test_dry_run_changes_nothing(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    wt = add_spoke(repo, "agent-a")
    commit_file(wt, "a.txt", "a\n", "spoke a")
    squash_onto_main(repo, "a.txt", "a\n")

    assert rw.main(["--repo", str(repo)], now=LATER) == 0
    assert wt.exists()
    assert git(repo, "branch", "--list", "worktree-agent-a")
    out = capsys.readouterr().out
    assert "reclaim  worktree  agent-a" in out
    assert "dry run" in out


def test_apply_removes_and_archives(repo: Path) -> None:
    wt = add_spoke(repo, "agent-a")
    tip = commit_file(wt, "a.txt", "a\n", "spoke a")
    squash_onto_main(repo, "a.txt", "a\n")
    kept = add_spoke(repo, "agent-b")
    commit_file(kept, "b.txt", "b\n", "spoke b")

    assert rw.main(["--repo", str(repo), "--apply"], now=LATER) == 0

    assert not wt.exists()
    assert not git(repo, "branch", "--list", "worktree-agent-a")
    assert git(repo, "rev-parse", "refs/archive/worktree-agent/worktree-agent-a") == tip
    assert kept.exists()
    assert git(repo, "branch", "--list", "worktree-agent-b")


def test_runs_from_inside_a_worktree(repo: Path) -> None:
    wt = add_spoke(repo, "agent-a")
    commit_file(wt, "a.txt", "a\n", "spoke a")
    squash_onto_main(repo, "a.txt", "a\n")
    other = add_spoke(repo, "agent-z")

    # Surveyed from a spoke's own checkout, the tool still finds the primary's
    # worktrees, and never offers the worktree it is running in.
    entries = by_name(rw.survey(other, now=LATER))
    assert entries["agent-a"].reason is None
    assert entries["agent-z"].reason == rw.CURRENT
