# My Team Is Better — operating manual

Product and architecture context lives in `docs/PRD.md` and `docs/ARCHITECTURE.md`; read
those first. This file governs *how* changes get made: a hub-and-spoke
coordinator/subagent process whose contracts are **enforced by hooks**, not just written
down, plus non-negotiable engineering standards for the Python and React sides.

Procedures live in skills, so they load only when used: `/orient` (session start),
`/delegate` (every delegation), `/ship` (PR to merged main), `/triage` (filing
findings). Exact per-language commands live in `.claude/rules/python.md` and
`.claude/rules/web.md`. Every spoke preloads the `spoke-protocol` skill.

---

## Starting a session

Run `/orient` before anything else. This project's memory is GitHub (issues, PRs,
labels) and `git log`, not conversation history: a fresh or just-cleared session
reconstructs state from them rather than asking the founder to re-explain it. `/orient`
reports what other sessions have in flight, what just landed and what it flagged, open
and claimed issues, untracked gaps, and which files are at collision risk.

If something real surfaces with no tracking issue, file it (`/triage`) before starting
unrelated work. `ingest_season.py`'s hardcoded year range was mentioned in three places
before anyone filed it (#9); don't let a gap get rediscovered a third time.

There is no separate delegation log. Merged PR descriptions carry the verification
record (`/ship`'s template), because they're linked to the diff and checked by CI.

## Several sessions at once

Three or four coordinator sessions usually run in parallel, each in its own git worktree.

- **Claim before you start.** `/delegate` adds the `in-progress` label and a claim
  comment naming the files you expect to touch. Don't start an issue someone has claimed.
- **Hot files** — `contracts.py`, `apps/api/src/api/models.py`,
  `apps/web/src/lib/api/types.ts`, `docs/ARCHITECTURE.md`, `.github/workflows/ci.yml` —
  are touched by roughly a quarter of all PRs. When another in-flight branch touches one,
  sequence the work (merge theirs, rebase) instead of racing it.
- **The git stash is shared by every worktree.** A hook blocks bare `git stash` and
  `git stash pop`; use a WIP commit.
- **Spoke worktrees branch from your `HEAD`** (`worktree.baseRef: "head"` in
  `.claude/settings.json`). Commit contract changes before delegating; uncommitted work
  isn't carried over.
- **Every spoke gets its own scratch directory** (the brief's `scratch_dir`, checked).
- **Picking up a process change** (this file, `.claude/`): merge `main` into your branch.
  Agent definitions, skills and hook settings reload live. CLAUDE.md and rules load at
  session start, so start a fresh session to get those.

---

## Engineering standards (apply to every change, not just new code)

These are standing rules, not a one-time setup task. A brief that would violate one is
mis-scoped: fix the brief, don't ship the violation.

- **TDD.** Write the failing test first, then implement against it. A brief's rubric
  names the tests; a return's `tests_run` records the red run and every command actually
  executed, never a claimed-but-unrun test.
- **CI gates everything.** `.github/workflows/ci.yml` runs on every PR into `main` and
  every push to `main`, and nothing merges with a red check. Known exceptions, listed so
  nobody assumes more coverage than exists:
  - the persona smoke eval step always skips in CI, because there is no API key secret
    (#203).

  A new app gets its own CI job with its first line of code. The process hooks have one
  (`claude-process`).
- **`main` is protected by process and a hook.** GitHub can't enforce branch protection
  on this private repo without GitHub Pro; the founder chose to stay private. Every
  change goes through a feature branch, a PR and green CI. `.claude/hooks/guard_bash.py`
  blocks pushes to `main` from any session. If the repo goes public or moves to Pro, turn
  on a ruleset requiring the CI jobs.
- **Python side**: `uv`; `mypy --strict` across module boundaries; `import-linter` for
  enforced boundaries; `pytest`; ruff; pre-commit mirroring CI. Commands:
  `.claude/rules/python.md`.
- **React/TypeScript side**: TypeScript strict; ESLint + `typescript-eslint` (never the
  deprecated TSLint); `dependency-cruiser` for enforced boundaries; Vitest + React
  Testing Library; Prettier; the Storybook build and its a11y tests as CI gates
  (Storybook coverage is a project goal per the PRD). Commands: `.claude/rules/web.md`.
- **Modularity is enforced, not just written down**, on both sides. A boundary stated in
  prose and never checked erodes by the third round.
- **Secrets**: never run `apps/api`'s tests from a checkout containing `apps/api/.env`.
  Its persona integration test makes a real Claude call and rewrites a production
  Postgres row (details in `spoke-protocol`).

---

## Roles

**The main session is the coordinator (the hub).** Subagents are spokes: fresh context
each time, they see only their brief plus CLAUDE.md, the rules and the preloaded
`spoke-protocol`, and only their final message comes back.

Start **coarse, deliberately.** Split an owner only when a real seam appears with its own
checked boundary, not preemptively. `packages/cfb-engine` earned four spokes because it
has four independent modules behind `import-linter` contracts.

| Agent | Owns | Must not touch |
|---|---|---|
| `api-agent` | `apps/api/` | `apps/web/`, `packages/cfb-engine/`, `.github/`, branch protection |
| `web-agent` | `apps/web/` | `apps/api/`, `packages/cfb-engine/`, `.github/`, branch protection |
| `ingest-agent` | `cfb_strength/ingest/`, `data/raw/` | ratings/, evidence/, mcp_server/, contracts.py, db/ |
| `ratings-agent` | `cfb_strength/ratings/` | ingest/, evidence/, mcp_server/, contracts.py, db/ |
| `evidence-agent` | `cfb_strength/evidence/` | ingest/, ratings/, mcp_server/, contracts.py, db/ |
| `mcp-agent` | `cfb_strength/mcp_server/` + its integration test | everything else |
| `validator` | nothing (read-only) | everything — golden dataset + persona smoke eval |
| `reviewer` | nothing (read-only) | everything — independent review of a diff and its seams |

The exact globs live in `.claude/ownership.json`, which the edit-scope hook and the
brief validator read. Coordinator-owned: everything no agent owns (this file, `.claude/`,
`.github/`, `docs/`, `render.yaml`, `contracts.py`, `db/`, `cli.py`, `config.py`,
`credit_math.py`). `.claude/hooks/tests/test_ownership.py` keeps this table, the JSON and
`.claude/agents/*.md` in step, so an agent can't exist in one place and be missing from
another (#105).

---

## What is enforced, and what is still prose

| Rule | Enforced by | Mode |
|---|---|---|
| A spoke's edits stay inside its owned paths | PreToolUse `guard_edit_scope.py` | **warn**: a note in the spoke's context plus a log at `<git-common-dir>/claude-hooks/scope-warnings.jsonl`. Flip `edit_scope_mode` to `block` once the log stays clean (#205) |
| No push to `main`; no shared-stash use | PreToolUse `guard_bash.py` | block |
| Brief shape; scope inside ownership; own scratch dir | `delegation.py render-brief` | block (the brief won't render) |
| Return shape and its semantic rules | SubagentStop `delegation.py` sends the errors back to the spoke (2 retries); the coordinator re-checks with `delegation.py validate-return` | block; still invalid = `malformed-return` |
| Agents, ownership map and Roles table agree | `claude-process` CI job | block |
| No merge-conflict markers land | `claude-process` CI job | block |

What these don't guarantee:
- Claude Code can't force a subagent's output format, so the return check runs after the
  fact and feeds errors back to the spoke (retry with feedback).
- A hook's notes reach the user, not the coordinator model, so `/delegate` re-validates
  every return with the CLI.
- Writes through Bash bypass the edit guard; the return check flags `files_changed`
  outside ownership instead.

Everything else in this file is prose.

---

## The delegation contract (v2)

Use `/delegate`. In short:

1. **Briefs are JSON** against `.claude/schemas/brief.schema.json`, rendered to the
   prompt by `delegation.py render-brief`, never hand-written prose. Rendering makes
   every brief the same shape and checks scope, base commit, scratch dir, concurrency
   and, for gate work, the threat model and review-round cap.
2. **Returns are one fenced JSON block** against `.claude/schemas/return.schema.json`.
   The SubagentStop hook makes the spoke fix an invalid one, and the coordinator validates
   it again with `delegation.py validate-return`. Worked examples:
   `.claude/schemas/examples/`.
3. **The coordinator tells apart three outcomes:**
   - the round failed: `status: failure` with a `failure_type` and `retryable`;
   - it succeeded: `status: success` with no blocking findings;
   - it succeeded but the brief was wrong: `success` plus `brief_defects` (#96).

   Findings route by severity: `blocking` → the next round, `pre-existing` → `/triage`,
   `nit` → usually nowhere.
4. **A validated return proves shape, not truth.** The coordinator re-runs the rubric's
   gate commands itself before shipping.

---

## Routing table (dynamic selection)

Don't fan out on work that didn't need fanning out; that's the most common failure in
this architecture.

| Request shape | Invoke | Skip |
|---|---|---|
| Anything inside `apps/api/` | `api-agent` | web-agent |
| Anything inside `apps/web/` | `web-agent` | api-agent |
| Anything inside `packages/cfb-engine/` | the owning engine agent (Roles) | api-agent, web-agent |
| "Is the ranking / persona still correct?" | `validator` | — |
| "Is this done?" | `reviewer` + `validator` in parallel; the reviewer gets only the brief and the diff | — |
| Pre-existing findings from any return, or an untracked gap | coordinator via `/triage` | all spokes |
| Persona *voice/tone quality* ("does this read as a good bar-stool guy?") | **coordinator directly** — a continuous, subjective, iterative judgment, not a scoped task | all spokes, until there is a specific, scoped prompt change to delegate |
| Why a ranking disagrees with known outcomes | **coordinator directly** | ratings-agent, until there's a specific hypothesis to implement |
| Typo, rename, one-line fix, config change | **nobody** — coordinator does it inline | all |
| A contract (shared type/schema) needs a new field | coordinator amends and commits it, then re-delegates every affected spoke | — |

---

## Error handling

All error handling routes through the coordinator; subagents never retry each other.

- **Malformed return** (the hook's retries ran out): retry once with a rewritten brief,
  or substitute an agent.
- **`retryable: true`**: one retry with `attempted` and `alternatives` appended.
- **`contract-insufficient`**: amend the contract, then re-delegate.
- **`scope-collision`**: split the round by owner.
- **`brief-mis-scoped`**: the brief asked for something the spoke can't or shouldn't do as
  written, often diagnosis that belongs with the coordinator. Do that part yourself, then
  re-brief a specific change.
- **Review rounds** stop at the gate's `max_review_rounds`; what remains becomes issues.

Silently suppressing a failure (treating an empty result as success) and aborting a whole
round because one spoke failed are both anti-patterns. A degraded round with a named gap
beats a dead round.
