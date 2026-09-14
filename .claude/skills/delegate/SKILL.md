---
name: delegate
description: Hand a scoped task to one of this repo's spokes (api-agent, web-agent, ingest/ratings/evidence/mcp-agent, reviewer, validator) — route it, claim the issue, write a schema-checked brief and render it, launch, then act on the hook-validated return. Use for every delegation in this repo.
argument-hint: "[issue-number] [agent]"
---

# Delegate a round

Arguments, if given: `$ARGUMENTS` (issue number, then agent).

## 1. Should this be delegated at all?

Use CLAUDE.md's routing table. Do it inline instead for a typo, a rename, a one-line fix
or a config change. Keep persona voice judgments and open-ended "why is the ranking
wrong" diagnosis with the coordinator. Don't fan out work that didn't need it. One
issue normally means one implementation spoke, then reviewer and validator.

## 2. Claim the issue (concurrent sessions)

```bash
gh issue view <n> --json labels,comments   # already claimed? then pick other work
gh label create in-progress --color FBCA04 --description "Claimed by a running coordinator session" 2>/dev/null || true
gh issue edit <n> --add-label in-progress
gh issue comment <n> --body "Claimed: worktree <path>, branch <branch>. Expected to touch: <files>."
```

If any expected file is a hot file (`contracts.py`, `apps/api/src/api/models.py`,
`apps/web/src/lib/api/types.ts`, `docs/ARCHITECTURE.md`, `ci.yml`) and `/orient` showed
another in-flight branch touching it, sequence the work rather than racing it.

## 3. Prepare the base

- Commit any contract change (contracts.py, schema.sql, API models) **before**
  delegating. Worktree spokes branch from your `HEAD` (`worktree.baseRef: "head"`), and
  uncommitted work isn't carried.
- `git rev-parse HEAD` becomes the brief's `base_sha`.
- **Check every numeric premise** the rubric depends on (a precision, a threshold, a
  count, "this makes it match") with a quick script over real fixture data. Paste the
  measured numbers into `contract`. A hand-checked example row proves nothing: one
  unchecked "3 decimals fixes it" cost #183 a full round.

## 4. Write the brief as JSON

Save it as `<scratchpad>/briefs/<issue>-<agent>-r<round>.json`. It must conform to
`.claude/schemas/brief.schema.json`. Worked example:
`.claude/schemas/examples/brief.api-agent.json`.

- `objective`: the outcome and its quality bar, not a step-by-step procedure.
- `contract`: the interface slice verbatim, plus measured numbers. The spoke sees nothing
  else.
- `scope`: inside the agent's `owns` in `.claude/ownership.json` (checked). Split a task
  that crosses owners into one round per owner.
- `rubric`: name the tests written first, the gate commands, and any sabotage
  expectations.
- `scratch_dir`: unique per spoke, e.g. `<scratchpad>/<issue>-<agent>-r<round>`.
- `concurrency`: what else is running (from `/orient` and your own parallel spokes) and
  which files it touches.
- `gate`: **required for any round that builds or tightens an enforcement check.** The
  default wording that has worked here: threat model "stops accidental erosion; deliberate
  evasion must leave a visible trace (eslint-disable, root-config edit, eval, runtime key
  construction, test-file code)"; blocking "an ordinary accidental escape, a false
  positive on legitimate code, or a vacuous check"; `max_review_rounds` 3. Also require
  false-positive probes on ordinary code.

## 5. Render and launch

```bash
uv run --script .claude/hooks/delegation.py render-brief <scratchpad>/briefs/<file>.json
```

Fix every error it prints. Pass stdout **verbatim** as the Agent prompt, with
`subagent_type` set to the brief's agent.

- Parallel spokes: put all the Agent calls in one message. Give writers that could touch
  the same checkout `isolation: "worktree"`.
- Reviewer: brief it with the diff range (`<base_sha>...<head>`) and the implementation
  brief's objective and rubric only. Never include the implementer's return or your
  reasoning; it reviews as an independent instance.

## 6. When the spoke returns

The SubagentStop hook has already validated the return. A "validated" system message
means the shape is right. A "malformed-return" message means treat the round as failed.
Shape isn't truth, so before acting:

1. Re-run the rubric's gate commands yourself in the checkout that has the change.
2. Diff against `base_sha`, not `main`, and take only the spoke's own commits or files.
3. Read any scope warnings (in the system message, and
   `<git-common-dir>/claude-hooks/scope-warnings.jsonl`).

Then act on what came back:

| Return | Coordinator action |
|---|---|
| success, no blocking findings | reviewer + validator in parallel (step 5), then `/ship` |
| blocking findings | next round (`round` + 1) with the findings pasted into `contract`; stop at the gate's `max_review_rounds` and file what remains |
| pre-existing findings | `/triage`, once per round, batched |
| brief_defects | fix the brief now; if the same defect recurs, fix this skill or the agent definition |
| contract_gaps / contract-insufficient | amend the contract yourself, commit, re-delegate every affected spoke |
| failure, `retryable: true` | one retry, with the failure's `attempted` and `alternatives` appended |
| scope-collision | split the round, or route that part to its owner |
| blocked-by-missing-input / tool-or-environment-failure | supply the input or fix the environment, or substitute an agent; otherwise proceed with a named gap |

Never abort a whole round because one spoke failed, and never treat an empty result as
success. A degraded round with a named gap beats a dead round.

## 7. Record

Keep the validated return JSON; `/ship` puts it in the PR description. When the work
merges or is abandoned, remove the `in-progress` label.
