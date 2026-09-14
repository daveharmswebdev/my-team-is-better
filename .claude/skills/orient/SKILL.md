---
name: orient
description: Reconstruct this repo's current state at the start of a session or after /clear — what other concurrent sessions have in flight, what just landed and what it flagged, open and claimed issues, untracked gaps, and which files are at collision risk. Run it before starting any work.
context: fork
agent: general-purpose
allowed-tools: Bash(git *) Bash(gh *) Read Grep Glob
---

You are orienting a coordinator session that is about to start work on this repo. Its
memory is GitHub plus git, not conversation history. Several coordinator sessions run
concurrently, each in its own git worktree. You are **read-only**: never file, label,
comment, commit or push.

## Snapshot taken just before you started

Branch and position: !`git status -sb --ahead-behind`

Worktrees, one per running or parked session: !`git worktree list`

Open pull requests:
!`gh pr list --state open --limit 30 --json number,title,headRefName,isDraft --template '{{range .}}#{{.number}} {{.headRefName}} draft={{.isDraft}} :: {{.title}}{{"\n"}}{{end}}'`

Claimed issues (label `in-progress`):
!`gh issue list --state open --label in-progress --limit 30 --json number,title --template '{{range .}}#{{.number}} {{.title}}{{"\n"}}{{end}}'`

Open issues:
!`gh issue list --state open --limit 150 --json number,title,labels --template '{{range .}}#{{.number}} [{{range .labels}}{{.name}} {{end}}] {{.title}}{{"\n"}}{{end}}'`

Recently merged:
!`gh pr list --state merged --limit 8 --json number,title,mergedAt --template '{{range .}}#{{.number}} {{.mergedAt}} {{.title}}{{"\n"}}{{end}}'`

`main`: !`git log --oneline -12 origin/main`

## Work to do

1. Run `git fetch --quiet origin`. For every branch in the worktree list and every open
   PR, run `git diff --name-only origin/main...<branch>` (use `origin/<headRefName>`
   for a PR whose branch isn't local). Note each claimed issue's claim comment:
   `gh issue view <n> --comments`.
2. Read the last five merged PR descriptions (`gh pr view <n> --json body`). Pull out
   anything they flagged: `contract_gaps`, `brief_defects`, pre-existing findings, and
   "after deploy" checks. For each, check whether an issue tracks it.
3. Look for real gaps with no issue: `git grep -nE "known gap|not yet|TODO|FIXME"` in
   `docs/` and `CLAUDE.md`, plus anything step 2 surfaced. Confirm with
   `gh issue list --state all --search "<keywords>"` before calling one untracked.
4. Group the open issues into clusters that share a root cause, where one design flaw
   is being fixed one symptom at a time (e.g. several persona grounding bugs).

## Output (under 60 lines, this exact shape)

```
## Repo state — <date>
**This checkout:** <branch>, <ahead/behind origin/main>, <clean|dirty>

**In flight elsewhere**
| Worktree / PR | Branch | Issue | Files touched (top 5) |

**Collision risk:** files touched by more than one in-flight branch, and any in-flight
branch touching a hot file (packages/cfb-engine/src/cfb_strength/contracts.py,
apps/api/src/api/models.py, apps/web/src/lib/api/types.ts, docs/ARCHITECTURE.md,
.github/workflows/ci.yml). "None" if none.

**Landed recently:** #n title — what it flagged, and whether that is tracked

**Open work, unclaimed:** by cluster; mark design-flaw clusters; include labels

**Untracked gaps:** each with evidence (file:line or PR #) — recommend filing via /triage

**Suggested next:** 1–3 items, each with a one-line reason, avoiding claimed work and
collision-risk files
```

Report only what the commands showed. If a command failed, say which one and continue.
