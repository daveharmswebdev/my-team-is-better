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


@pytest.fixture(autouse=True)
def no_github(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """`main` asks GitHub which merged PR holds a tip (#391); no test may reach it.
    Returns the shas asked about, and answers "none"."""
    asked: list[str] = []

    def lookup(repo: Path, sha: str) -> int | None:
        asked.append(sha)
        return None

    monkeypatch.setattr(rw, "merged_pr_via_gh", lookup)
    return asked


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


def test_fresh_spoke_on_an_old_base_is_kept(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Review of #387: a spoke started just now on a base commit days old. The commit
    # time says "old", so the new worktree's own reflog entry is what keeps it.
    monkeypatch.setenv("GIT_COMMITTER_DATE", "@1700000000 +0000")
    commit_file(repo, "old.txt", "old\n", "an old base")
    publish_main(repo)
    monkeypatch.delenv("GIT_COMMITTER_DATE")
    add_spoke(repo, "agent-fresh")

    assert by_name(rw.survey(repo))["agent-fresh"].reason == rw.RECENT


def test_prunable_worktree_is_kept_without_aborting(repo: Path) -> None:
    # Its directory is gone but git still lists it; the survey reports it and goes on.
    gone = add_spoke(repo, "agent-gone")
    wt = add_spoke(repo, "agent-a")
    commit_file(wt, "a.txt", "a\n", "spoke a")
    squash_onto_main(repo, "a.txt", "a\n")
    subprocess.run(["rm", "-rf", str(gone)], check=True)

    entries = by_name(rw.survey(repo, now=LATER))
    assert entries["agent-gone"].reason == rw.PRUNABLE
    assert entries["agent-a"].reason is None


def test_apply_keeps_a_non_spoke_branch_checked_out_in_an_agent_worktree(repo: Path) -> None:
    # A fork's agent-* worktree can hold a coordinator branch (issue-339-...); only
    # the worktree goes, the branch stays.
    wt = add_spoke(repo, "agent-k", branch="issue-999-pr-branch")
    commit_file(wt, "k.txt", "k\n", "spoke k")
    squash_onto_main(repo, "k.txt", "k\n")

    assert rw.main(["--repo", str(repo), "--apply"], now=LATER) == 0

    assert not wt.exists()
    assert git(repo, "branch", "--list", "issue-999-pr-branch")


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


def test_tip_in_a_merged_pr_is_a_candidate(repo: Path) -> None:
    # #391: the coordinator fixed the spoke's file in a review round before the PR
    # squash-merged, so merging the spoke tip into main conflicts and the tree test
    # keeps it, though the PR that carried the tip merged.
    wt = add_spoke(repo, "agent-m")
    tip = commit_file(wt, "m.txt", "spoke draft\n", "spoke m")
    squash_onto_main(repo, "m.txt", "reviewed version\n")

    def merged(r: Path, sha: str) -> int | None:
        return 383 if sha == tip else None

    entry = by_name(rw.survey(repo, now=LATER, merged_pr=merged))["agent-m"]
    assert entry.reason is None
    assert entry.merged_pr == 383


def test_tip_in_no_merged_pr_is_still_kept(repo: Path) -> None:
    wt = add_spoke(repo, "agent-n")
    commit_file(wt, "n.txt", "n\n", "spoke n")

    entry = by_name(rw.survey(repo, now=LATER, merged_pr=lambda r, sha: None))["agent-n"]
    assert entry.reason == rw.NOT_IN_MAIN
    assert entry.merged_pr is None


def test_merged_pr_never_overrides_the_other_guards(repo: Path) -> None:
    # Dirty, recent and locked are about the worktree, not its history: a merged PR
    # doesn't make unreturned work, a just-started spoke or a lock safe to remove.
    dirty = add_spoke(repo, "agent-dirty")
    (dirty / "scratch.txt").write_text("unreturned\n")
    add_spoke(repo, "agent-new")
    locked = add_spoke(repo, "agent-lock")
    git(repo, "worktree", "lock", str(locked))
    asked: list[str] = []

    def merged(r: Path, sha: str) -> int | None:
        asked.append(sha)
        return 1

    entries = by_name(rw.survey(repo, merged_pr=merged))
    assert entries["agent-dirty"].reason == rw.DIRTY
    assert entries["agent-new"].reason == rw.RECENT
    assert entries["agent-lock"].reason == rw.LOCKED
    assert asked == []


def test_lookup_only_runs_when_the_tree_test_fails(repo: Path) -> None:
    wt = add_spoke(repo, "agent-a")
    commit_file(wt, "a.txt", "a\n", "spoke a")
    squash_onto_main(repo, "a.txt", "a\n")
    asked: list[str] = []

    def merged(r: Path, sha: str) -> int | None:
        asked.append(sha)
        return None

    assert by_name(rw.survey(repo, now=LATER, merged_pr=merged))["agent-a"].reason is None
    assert asked == []


def test_orphan_branch_in_a_merged_pr_is_a_candidate(repo: Path) -> None:
    wt = add_spoke(repo, "agent-o")
    tip = commit_file(wt, "o.txt", "draft\n", "spoke o")
    squash_onto_main(repo, "o.txt", "final\n")
    git(repo, "worktree", "remove", str(wt))

    entry = by_name(rw.survey(repo, now=LATER, merged_pr=lambda r, sha: 7 if sha == tip else None))[
        "worktree-agent-o"
    ]
    assert entry.reason is None
    assert entry.merged_pr == 7


def test_main_asks_github_and_names_the_pr(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    wt = add_spoke(repo, "agent-g")
    tip = commit_file(wt, "g.txt", "draft\n", "spoke g")
    squash_onto_main(repo, "g.txt", "final\n")
    monkeypatch.setattr(rw, "merged_pr_via_gh", lambda r, sha: 383 if sha == tip else None)

    assert rw.main(["--repo", str(repo)], now=LATER) == 0
    assert "reclaim  worktree  agent-g  (merged in #383)" in capsys.readouterr().out


def test_no_github_flag_skips_the_lookup(repo: Path, no_github: list[str]) -> None:
    wt = add_spoke(repo, "agent-h")
    commit_file(wt, "h.txt", "draft\n", "spoke h")
    squash_onto_main(repo, "h.txt", "final\n")

    assert rw.main(["--repo", str(repo), "--no-github"], now=LATER) == 0
    assert no_github == []


@pytest.mark.parametrize(
    ("returncode", "stdout", "expected"),
    [
        (0, '[{"number": 383, "baseRefName": "main", "commits": [{"oid": "TIP"}]}]', 383),
        # Search matched the sha in some other text, but the PR doesn't hold the commit.
        (0, '[{"number": 12, "baseRefName": "main", "commits": [{"oid": "other"}]}]', None),
        # Merged into a feature branch (a stacked PR), so its work isn't in main.
        (0, '[{"number": 9, "baseRefName": "issue-1", "commits": [{"oid": "TIP"}]}]', None),
        # A failed gh never counts, whatever it printed.
        (1, '[{"number": 383, "baseRefName": "main", "commits": [{"oid": "TIP"}]}]', None),
        (0, "[]", None),
        # gh missing, offline or unauthenticated: every error keeps.
        (1, "", None),
        (0, "not json", None),
    ],
)
def test_merged_pr_via_gh_parses_and_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    returncode: int,
    stdout: str,
    expected: int | None,
) -> None:
    monkeypatch.undo()  # the autouse fake; this test exercises the real function
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, returncode, stdout=stdout, stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert rw.merged_pr_via_gh(tmp_path, "TIP") == expected
    assert calls and calls[0][:4] == ["gh", "pr", "list", "--state"]
    assert "TIP" in calls[0]
    assert calls[0][calls[0].index("--base") + 1] == "main"


def test_merged_pr_via_gh_without_gh_installed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.undo()

    def missing(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError("gh")

    monkeypatch.setattr(subprocess, "run", missing)
    assert rw.merged_pr_via_gh(tmp_path, "TIP") is None
