---
name: ship
description: Take finished work from a feature branch to merged main safely in this repo — a draft PR early so CI runs during review, a bounded PR description carrying the verification record, green CI, squash merge with stacked-PR handling, a post-merge Render deploy check, and releasing the issue claim.
argument-hint: "[issue-number]"
---

# Ship

Arguments, if given: `$ARGUMENTS`.

## 1. Open a draft PR as soon as round 1 is green locally

CI runs only on PRs into `main`. Waiting for review to finish before opening one means
Linux CI first sees the branch after several rounds (#157), so open it early:

```bash
git push -u origin <branch>                     # never main: a hook blocks it
gh pr create --draft --base main --title "<imperative summary> (closes #n)" --body-file <scratchpad>/pr-<n>.md
```

Don't stack PRs unless the dependency is real: a PR based on another branch gets **no
CI** at all.

## 2. The description (update it every round with `gh pr edit <pr> --body-file`)

Keep everything outside `<details>` under about 4,000 characters. Readers need the
why, the what and the proof, not the round-by-round story.

```markdown
## Why
<the user-visible problem, with evidence>

## What changed
<bullets by area; name accepted trade-offs explicitly>

## Verification (re-run by the coordinator, not only the spoke)
- `<command>` — <result>

## Delegation record
contract_gaps: none | <list>
brief_defects: none | <list>
Findings filed: #n (pre-existing, <category>) … | none

<details><summary>Validated returns and review rounds</summary>

<one fenced json block per spoke return, labeled by agent and round>
</details>

Closes #n
```

The `pr-body` CI check (#374) fails a PR whose description lacks `## Why`,
`## What changed`, `## Verification`, or an issue reference: `Closes #n` (or Fixes,
Resolves), a line starting `Part of #n` or `Refs #n` for one step of an issue that stays
open, or `No issue: <reason>` for untracked work. Editing the description re-runs it.
Check locally first: `python3 .claude/hooks/check_pr_body.py --body-file <file>`.

Add the attribution lines your session's instructions give you.

## 3. Merge

1. `gh pr ready <pr>`, then `gh pr checks <pr> --watch`. Every job must be green,
   `e2e` included. Red means fix, never merge.
2. Check for dependents: `gh pr list --base <branch>`.
   - **None:** `gh pr merge <pr> --squash`, then delete the branch (step 3).
   - **Some:** retarget each dependent first (`gh pr edit <dep> --base main`), then merge
     **without** `--delete-branch`. Rebase each dependent with
     `git rebase --onto origin/main <old-base-tip> <dep-branch>` and
     `git push --force-with-lease`, which also fires its CI. Delete the old branch last
     (step 3). (`--delete-branch` on a base PR closed #174 for good.)
3. Delete the merged branch yourself; don't rely on `gh pr merge --delete-branch`. After
   merging, `gh` switches this checkout to `main`. With several worktrees running,
   another one usually has `main` checked out, so that switch fails
   (`'main' is already used by worktree`). The merge still lands, but `gh` skips the
   branch deletion and leaves the branch on GitHub (#241).
   ```bash
   gh pr view <pr> --json state -q .state          # MERGED, before deleting anything
   git push origin --delete <branch>
   git fetch -q origin && git switch --detach origin/main && git branch -D <branch>
   ```

## 4. After the merge

- `gh issue edit <n> --remove-label in-progress` for each issue it touched. A closed
  issue moves to Done on the board by itself; one that stays open goes back with
  `uv run .claude/hooks/board.py <n> --status Todo`.
- **Reclaim finished spoke worktrees** (#339):
  `git fetch --quiet origin && uv run .claude/hooks/reclaim_worktrees.py --apply`.
  It removes only clean `agent-*` worktrees and orphan `worktree-agent-*` branches whose
  work is already in `origin/main` and that are more than a day old. It archives each
  branch tip under `refs/archive/worktree-agent/` first. This round's own spokes are too
  new, so a later `/ship` collects them.
- **Verify the deploys.** Don't assume auto-deploy fired; it has stalled before. Work
  out first which services should deploy, then check only those, with the Render MCP's
  `list_deploys`: api `srv-dahkq61594qs73fe0mrg`, web `srv-dahkq61594qs73fe0mo0`, so no
  `list_services` call is needed:
  - The API deploys only when the diff touches its `buildFilter` (`apps/api/**`,
    `packages/cfb-engine/**`, `pyproject.toml`, `uv.lock`) or `render.yaml`. With
    `render.yaml` in the diff the trigger is `blueprint_sync`, otherwise `new_commit`.
  - The web service deploys only if `apps/web/` changed (`rootDir: apps/web`).
  - Neither: nothing deploys (a `.claude/`- or `docs/`-only merge). Say so on the PR and
    skip the calls.
  - Use `limit: 1` and compare only the commit id and `status`. Each row carries the
    full squash message, 2–3k tokens (#400). With `render.yaml` in the diff use
    `limit: 3`, because a harmless same-commit `build_failed` can sit beside the live
    one (#297).
  - Nothing within about 10 minutes when one was expected: trigger it manually and note
    it on the PR.
- Run any "after deploy" check the description promised, and report the result on the
  PR.
- If the merge changed `CLAUDE.md` or `.claude/`, say so on the PR. Other running
  sessions pick it up by merging `main`; CLAUDE.md and rules need a fresh session.
