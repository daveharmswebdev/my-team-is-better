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

Add the attribution lines your session's instructions give you.

## 3. Merge

1. `gh pr ready <pr>`, then `gh pr checks <pr> --watch`. Every job must be green,
   `e2e` included. Red means fix, never merge.
2. Check for dependents: `gh pr list --base <branch>`.
   - **None:** `gh pr merge <pr> --squash --delete-branch`.
   - **Some:** retarget each dependent first (`gh pr edit <dep> --base main`), then merge
     **without** `--delete-branch`. Rebase each dependent with
     `git rebase --onto origin/main <old-base-tip> <dep-branch>` and
     `git push --force-with-lease`, which also fires its CI. Delete the old branch last.
     (`--delete-branch` on a base PR closed #174 for good.)

## 4. After the merge

- `gh issue edit <n> --remove-label in-progress` for each issue it touched.
- **Verify the deploys.** Don't assume auto-deploy fired; it has stalled before. Use the
  Render MCP (`list_services`, then `list_deploys`) for `my-team-is-better-api` and
  `my-team-is-better-web`:
  - `render.yaml` in the diff: the API deploys with trigger `blueprint_sync`.
  - `render.yaml` not in the diff: the API deploys with trigger `new_commit`.
  - The web service deploys only if `apps/web/` changed (`rootDir: apps/web`).
  - Nothing within about 10 minutes when one was expected: trigger it manually and note
    it on the PR.
- Run any "after deploy" check the description promised, and report the result on the
  PR.
- If the merge changed `CLAUDE.md` or `.claude/`, say so on the PR. Other running
  sessions pick it up by merging `main`; CLAUDE.md and rules need a fresh session.
