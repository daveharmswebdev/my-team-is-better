# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Remove spoke worktrees and branches whose work is already in main (#339).

`/delegate` creates a worktree and a `worktree-agent-*` branch per spoke, and nothing
else ever deletes them: by 2026-10-19 there were 46 worktrees and 16 GB. This lists
what can go, and with `--apply` removes it. Dry run is the default.

    git fetch origin
    uv run .claude/hooks/reclaim_worktrees.py            # report only
    uv run .claude/hooks/reclaim_worktrees.py --apply    # remove the "reclaim" rows

Only `.claude/worktrees/agent-*` worktrees and `worktree-agent-*` branches with no
worktree are considered; a coordinator's own worktrees (`issue-349`, ...) never are.
One is kept, with the reason printed, when any of these holds:

- it is the worktree this command runs in, or it is locked;
- `git status --porcelain` is non-empty (a spoke's unreturned work);
- it was touched within `--min-age-hours` (default 24). A spoke that has just started
  sits clean at its base commit, which main already contains, so its age is the only
  thing that protects it;
- its work isn't in main.

"In main" can't be `git branch --merged`: PRs land by squash merge, so a spoke's commits
are never ancestors of main even once all their work is there. The test is instead
"merging the branch into main would change nothing": `git merge-tree --write-tree
<main> <branch>` must succeed and give exactly main's tree. A squash-merged branch
passes. A branch with any change main lacks, or one that conflicts with main, fails,
including a change main later reverted. Every error is in the keep direction. Main
is `origin/main`, so fetch first. A stale ref can only keep more.

Before a branch is deleted, its tip is saved under `refs/archive/worktree-agent/<branch>`,
so its commits stay reachable, the same as the founder's 2026-10-19 cleanup.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

WORKTREE_PREFIX = "agent-"
BRANCH_PREFIX = "worktree-agent-"
ARCHIVE_PREFIX = "refs/archive/worktree-agent/"
DEFAULT_MAIN = "origin/main"
DEFAULT_MIN_AGE_HOURS = 24.0

CURRENT = "the worktree this command runs in"
LOCKED = "locked"
DIRTY = "uncommitted changes"
RECENT = "touched too recently"
NOT_IN_MAIN = "has work that isn't in main"


@dataclass(frozen=True)
class Entry:
    kind: Literal["worktree", "branch"]
    name: str
    branch: str | None
    path: Path | None
    reason: str | None  # None: safe to reclaim


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=check, capture_output=True, text=True
    )


def _out(repo: Path, *args: str) -> str:
    return _git(repo, *args).stdout.strip()


def _in_main(repo: Path, main_ref: str, rev: str) -> bool:
    merged = _git(repo, "merge-tree", "--write-tree", main_ref, rev, check=False)
    if merged.returncode != 0:
        return False
    return merged.stdout.split("\n", 1)[0].strip() == _out(
        repo, "rev-parse", f"{main_ref}^{{tree}}"
    )


def _touched(repo: Path, ref: str, *paths: Path) -> float:
    """When `ref` last moved: its newest reflog entry, its tip's commit time, and the
    mtime of `paths`, whichever is latest. Not the mtime of git's own files: `git
    status` rewrites a worktree's index, and housekeeping rewrites reflog files."""
    latest = float(_out(repo, "log", "-1", "--format=%ct", ref))
    entry = _out(repo, "reflog", "-1", "--date=unix", "--format=%gd", ref)
    if entry.endswith("}") and "@{" in entry:
        latest = max(latest, float(entry.rsplit("@{", 1)[1][:-1]))
    return max([latest, *(p.stat().st_mtime for p in paths if p.exists())])


def _worktrees(repo: Path) -> list[dict[str, str]]:
    """`git worktree list --porcelain`, one dict per worktree."""
    blocks = _out(repo, "worktree", "list", "--porcelain").split("\n\n")
    out = []
    for block in blocks:
        record: dict[str, str] = {}
        for line in block.splitlines():
            key, _, value = line.partition(" ")
            record[key] = value
        if "worktree" in record:
            out.append(record)
    return out


def survey(
    repo: Path,
    main_ref: str = DEFAULT_MAIN,
    min_age_hours: float = DEFAULT_MIN_AGE_HOURS,
    now: float | None = None,
) -> list[Entry]:
    """Every spoke worktree and orphan spoke branch, with the reason to keep it, if any."""
    now = time.time() if now is None else now
    cutoff = now - min_age_hours * 3600
    common = Path(_out(repo, "rev-parse", "--path-format=absolute", "--git-common-dir"))
    current = Path(_out(repo, "rev-parse", "--show-toplevel")).resolve()
    spoke_root = (common.parent / ".claude" / "worktrees").resolve()

    entries: list[Entry] = []
    checked_out: set[str] = set()
    for record in _worktrees(repo):
        path = Path(record["worktree"]).resolve()
        branch = record.get("branch", "").removeprefix("refs/heads/") or None
        if branch:
            checked_out.add(branch)
        if path.parent != spoke_root or not path.name.startswith(WORKTREE_PREFIX):
            continue
        reason: str | None = None
        if path == current:
            reason = CURRENT
        elif "locked" in record:
            reason = LOCKED
        elif _out(path, "--no-optional-locks", "status", "--porcelain"):
            reason = DIRTY
        else:
            # The directory's mtime covers a spoke that hasn't moved HEAD yet.
            if _touched(path, "HEAD", path) > cutoff:
                reason = RECENT
            elif not _in_main(repo, main_ref, record["HEAD"]):
                reason = NOT_IN_MAIN
        entries.append(Entry("worktree", path.name, branch, path, reason))

    refs = _out(repo, "for-each-ref", "--format=%(refname:short)", f"refs/heads/{BRANCH_PREFIX}*")
    for branch in refs.splitlines():
        if branch in checked_out:
            continue
        if _touched(repo, f"refs/heads/{branch}") > cutoff:
            reason = RECENT
        elif not _in_main(repo, main_ref, branch):
            reason = NOT_IN_MAIN
        else:
            reason = None
        entries.append(Entry("branch", branch, branch, None, reason))
    return entries


def reclaim(repo: Path, entry: Entry) -> None:
    """Remove one entry `survey` cleared. `git worktree remove` without --force refuses
    a dirty worktree, a second check behind the survey's."""
    if entry.path is not None:
        _git(repo, "worktree", "remove", str(entry.path))
    if entry.branch is not None:
        tip = _out(repo, "rev-parse", f"refs/heads/{entry.branch}")
        _git(repo, "update-ref", f"{ARCHIVE_PREFIX}{entry.branch}", tip)
        _git(repo, "branch", "-D", entry.branch)


def main(argv: list[str] | None = None, now: float | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--repo", type=Path, default=Path(os.getcwd()))
    parser.add_argument("--main", default=DEFAULT_MAIN, help="ref holding main's work")
    parser.add_argument("--min-age-hours", type=float, default=DEFAULT_MIN_AGE_HOURS)
    parser.add_argument("--apply", action="store_true", help="remove the 'reclaim' rows")
    args = parser.parse_args(argv)

    if _git(args.repo, "rev-parse", "--verify", "--quiet", args.main, check=False).returncode:
        print(f"reclaim_worktrees.py: no ref {args.main!r}; run git fetch", file=sys.stderr)
        return 2

    entries = survey(args.repo, args.main, args.min_age_hours, now)
    for entry in entries:
        action = "reclaim" if entry.reason is None else "keep"
        detail = "" if entry.reason is None else f"  ({entry.reason})"
        print(f"{action:<8} {entry.kind:<9} {entry.name}{detail}")
        if entry.reason is None and args.apply:
            reclaim(args.repo, entry)

    count = sum(e.reason is None for e in entries)
    verb = "reclaimed" if args.apply else "to reclaim (dry run; --apply to act)"
    print(f"{count} {verb}, {len(entries) - count} kept")
    return 0


if __name__ == "__main__":
    sys.exit(main())
