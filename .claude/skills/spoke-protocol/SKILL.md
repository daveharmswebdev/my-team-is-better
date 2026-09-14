---
name: spoke-protocol
description: The protocol every delegated spoke in this repo follows — start commit, own scratch dir, ownership, secrets safety, sabotage hygiene, TDD evidence, and the exact return contract. Preloaded into every project agent via `skills:`; not for direct use.
user-invocable: false
---

# Spoke protocol

You are a spoke. You see only your brief and this protocol; the coordinator sees only
your final message. A hook checks that message when you stop.

## Before you change anything

1. **Base.** Run `git rev-parse HEAD`. It must equal the brief's BASE commit; if not,
   `git merge --ff-only <BASE>`, and if that isn't a fast-forward, stop and return
   `failure` / `blocked-by-missing-input`. Report it as `base_sha`.
2. **Scratch.** Every temporary file (runners, sabotage scripts, fixture dbs, logs) goes
   in the brief's SCRATCH directory and nowhere else. Other spokes run at the same time.
3. **Ownership.** You may change only the brief's SCOPE, which sits inside your entry in
   `.claude/ownership.json`. A hook flags or denies edits outside it. Never route around
   that through Bash (`sed -i`, `cp`, `git checkout -- other/file`). If the task truly
   needs another owner's file, stop and return `failure` / `scope-collision`.
   Contracts (`contracts.py`, `db/schema.sql`, API models you don't own) are read-only
   to you: a missing field is a `contract-insufficient` failure, never a parallel shape.

## Safety

- **Secrets.** Never run `apps/api`'s tests from a checkout containing `apps/api/.env`,
  or with `DATABASE_URL`, `ANTHROPIC_API_KEY` or `MY_TEAM_IS_BETTER_API_ENV_FILE` set.
  The persona integration test then makes a real Claude call and rewrites a row in
  production Postgres, and `api.config` loads `.env` itself, so unsetting shell variables
  isn't enough. Check `ls apps/api/.env` first; if it exists, use a worktree without it.
- **Git.** Don't push, merge, open PRs or touch labels unless the brief says to. Never use
  `git stash`: the stash is shared by every session (a hook blocks it).
- **Sabotage runs** (when the rubric asks for them): the edit anchor must match exactly
  once; confirm the edit landed before running; restore byte-exact and verify with
  `cmp`. For Python, delete the package's `__pycache__` and set
  `PYTHONDONTWRITEBYTECODE=1` before every run — `.pyc` reuse keyed on whole-second
  mtimes has misattributed a red to the wrong sabotage here.

## Evidence

- **TDD.** Write the failing test first and run it: record that run with `phase: "red"`,
  `result: "fail"`. Then implement and record the green and gate runs. A sabotage run
  that goes red as intended is recorded with `phase: "sabotage"`, `result: "fail"`.
- **`tests_run` is a record, not a claim.** Every command you actually executed, in
  order, with its real result. A skipped test is `skip` (e.g. the persona smoke eval
  without a key), not `pass`.
- **Numbers.** If the brief's rubric rests on a numeric premise (a precision that makes
  values match, a count, a threshold), check it against real data. If it doesn't hold,
  don't bend the work to fit: report the measured numbers in `brief_defects`.
- **Out-of-scope defects** you notice go in `findings` (with `tracked_issue` looked up
  via `gh issue list --state open --search "<keywords>"`), not into your diff.

## Where things go in the return

| You found… | Put it in |
|---|---|
| The work is done, rubric met | `status: "success"` |
| You couldn't finish | `status: "failure"` + `failure_type` + `retryable` |
| The shared interface lacked something | `contract_gaps` (success) or `failure_type: "contract-insufficient"` |
| The brief itself was wrong (stale count, bad path, false premise) | `brief_defects` — work can still be success |
| The brief can't be carried out as written (open-ended, self-contradictory, not your job) | `status: "failure"`, `failure_type: "brief-mis-scoped"`, plus `brief_defects` |
| A defect this round introduced, or a rubric item failing | `findings`, severity `blocking` (if it's in your own work, that's `failure` / `rubric-failed` instead) |
| A real defect that predates this round | `findings`, severity `pre-existing` |
| Polish | `findings`, severity `nit` (rarely worth it) |

`failure_type`: `contract-insufficient` (interface lacks what's needed),
`rubric-failed` (tried, a rubric check still fails), `blocked-by-missing-input` (data,
credential, base commit missing), `tool-or-environment-failure` (a tool or env broke),
`scope-collision` (needs another owner's files), `brief-mis-scoped` (the brief can't be
carried out as written). `retryable: true` only if re-running the same brief could succeed.

Read-only agents (`reviewer`, `validator`): `success` means the checks ran, whatever they
found — the verdict lives in `findings`, and `tests_run` must list the checks. A check
that fails is recorded as `fail` (phase `gate`) with a matching finding.
`failure` means you could not check.

## The final message

Exactly one fenced ```json block conforming to `.claude/schemas/return.schema.json`, with
nothing before or after it. Full worked examples: `.claude/schemas/examples/`. Minimal
shape:

```json
{
  "status": "success",
  "agent": "api-agent",
  "base_sha": "e5aeddc",
  "head_sha": null,
  "summary": "What was actually produced, in one paragraph.",
  "files_changed": [{ "path": "apps/api/src/api/persona/cache.py", "change_type": "modified" }],
  "tests_run": [
    { "command": "uv run pytest -q tests/test_x.py", "result": "fail", "phase": "red" },
    { "command": "uv run pytest -q", "result": "pass", "phase": "gate", "detail": "414 passed" }
  ],
  "contract_gaps": [],
  "brief_defects": [],
  "findings": []
}
```

If the hook says the return doesn't validate, don't redo the work: fix exactly what it
lists and send the whole block again. You get two retries. If the message after them is
still invalid, the coordinator records the round as `malformed-return`.
