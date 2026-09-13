# My Team Is Better — operating manual

Product/architecture context lives in `docs/PRD.md` and `docs/ARCHITECTURE.md` — read
those first. This file governs *how* changes get made from here on: a hub-and-spoke
coordinator/subagent process (same pattern proven in `../cfb-strength-orchestrated`,
adapted with JSON-Schema-validated inter-agent contracts) plus non-negotiable
engineering standards for both the Python and React sides.

---

## Starting a session (do this before anything else)

This project's memory is externalized on purpose — GitHub Issues/Milestones/PRs and
`git log`, not conversation history. A fresh or just-cleared session is expected to
reconstruct state from these, not ask the user to re-explain it:

1. `gh issue list --state open` — what's left, and read the open Sprint milestone
   (`gh api repos/:owner/:repo/milestones`) for the current sprint's framing.
2. `git log --oneline -15` — what actually landed on `main` recently.
3. `gh pr list --state merged --limit 5` and skim each merged PR's description (not
   just its title) — verification notes and any `contract_gaps` a spoke flagged live
   there, not in a separate log.
4. Check for open items with no issue yet: grep recent PR descriptions and
   `docs/ARCHITECTURE.md` for phrases like "not yet extended," "known gap," "TODO" —
   if something real surfaces with no tracking issue, **file one** before starting
   unrelated work, so it doesn't get rediscovered from scratch a third time. (This
   project already hit exactly this once: `packages/cfb-engine`'s `ingest_season.py`
   hardcoding `MIN_YEAR = 2000` / `MAX_YEAR = 2023` was mentioned in three separate
   places — `docs/ARCHITECTURE.md` §3.1, `render.yaml`'s build-command comment, and a
   PR description — before anyone filed it as a real issue. It's tracked as #9 now;
   check its current status there instead of re-deriving the gap from scratch again.)

There is no separate `docs/delegation-log.md` in this project (unlike
`../cfb-strength-orchestrated`, which used one) — merged PR descriptions serve that
role instead, since they're linked to the actual diff and checked by CI, which a
prose log entry isn't. Don't create a parallel log that duplicates what a PR
description already says; do create a GitHub issue for anything real that has no
tracking anywhere yet.

---

## Engineering standards (apply to every change, not just new code)

These are standing rules, not a one-time setup task. Any brief that would violate one
of these is mis-scoped — fix the brief, don't ship the violation.

- **TDD.** Write the failing test first, then implement against it. A brief's RUBRIC
  names the test(s) that must exist and pass; a RETURN's `tests_run` must reflect
  commands actually executed, never a claimed-but-unrun test.
- **CI gates everything.** `.github/workflows/ci.yml` runs on every PR and push to
  `main`. Nothing merges with a red check. Add a job to that workflow the moment a new
  app (`apps/api`, `apps/web`) gets its first line of code — don't let untested code
  accumulate ahead of its own CI job.
- **`main` is protected — process, not (yet) a GitHub-enforced gate.** GitHub blocks
  branch protection (both the classic API and the newer Rulesets API — checked
  directly, not assumed) on a private repo without GitHub Pro. Founder chose to stay
  private and skip the paid plan for now, so this is enforced by discipline: every
  change — including this one — goes through a feature branch, a PR, and a green CI
  run before merging, with no direct `git push` to `main`. If the repo goes public or
  moves to GitHub Pro later, flip on classic branch protection / a ruleset requiring
  the CI job(s) below — the workflow doesn't change, only the enforcement mechanism.
- **Python side**: `uv` for dependencies/workspace, `mypy --strict` on anything that
  crosses a module boundary (already true for `contracts.py`; extend to `apps/api`'s
  request/response models), `import-linter` for enforced (not just documented) module
  boundaries, `pytest`, pre-commit hooks running all of the above locally
  (`.pre-commit-config.yaml`).
- **React/TypeScript side**: TypeScript strict mode, ESLint + `typescript-eslint`
  (the modern successor to TSLint — never reach for the deprecated tool),
  `dependency-cruiser` for enforced module boundaries (the JS analogue of
  `import-linter` — same philosophy: a boundary stated in prose and never checked
  erodes by the third round), Vitest + React Testing Library for TDD, Prettier,
  Storybook build as a CI gate (not just local dev — Storybook coverage is a project
  goal in its own right, per the PRD).
- **Modularity is enforced, not just written down**, on both sides — this project
  already proved that principle in `packages/cfb-engine`'s `.importlinter` config;
  every new app extends it with its own checked tool rather than a "please don't
  import across this boundary" comment.

---

## Roles

**The main session is the coordinator (the hub).** Subagents are spokes: fresh
context each time, see only the brief they're given, return only their final message.

Starting **coarse, deliberately** — two implementation spokes, not one per module.
`packages/cfb-engine` earned its fine-grained split (`ingest-agent`/`ratings-agent`/
`evidence-agent`/`mcp-agent`) because it has four genuinely independent modules with a
real `import-linter` boundary between them. `apps/api` and `apps/web` don't have that
seam yet — split further only when a real one appears (e.g. the debate/tool-calling
logic in Architecture Brief §4.6 growing complex enough to deserve its own owner), not
preemptively.

| Agent | Owns | Must not touch |
|---|---|---|
| `api-agent` | `apps/api/` | `apps/web/`, `packages/cfb-engine/`, `.github/`, branch protection |
| `web-agent` | `apps/web/` | `apps/api/`, `packages/cfb-engine/`, `.github/`, branch protection |
| `validator` | nothing (read-only) | everything — golden dataset + persona smoke eval |
| `reviewer` | nothing (read-only) | everything — cross-cutting seams + standards compliance |

`packages/cfb-engine`'s existing ownership map (ingest/ratings/evidence/mcp-agent,
`contracts.py`/`schema.sql` coordinator-owned) is unchanged — see the agent
definitions in `.claude/agents/` (`ingest-agent.md`, `ratings-agent.md`,
`evidence-agent.md`, `mcp-agent.md`) for that layer; this table only covers the two
new apps. Every engine spoke named here must have a definition file there, and vice
versa (#105 was the one that didn't).

---

## The delegation contract: JSON Schema, not prose

Every brief and every spoke return is validated against a checked-in schema —
`.claude/schemas/brief.schema.json` and `return.schema.json`. **Be honest about what
this does and doesn't guarantee**: Task-tool subagents don't get native
`tool_choice`-forced structured output the way a raw Anthropic API call does — this is
schema-*disciplined prompting plus coordinator-side verification*, not a hard
API-level guarantee. Concretely:

1. The coordinator constructs every brief against `brief.schema.json`'s fields
   (`objective`, `contract`, `scope`, `negative`, `rubric`) before delegating.
2. Every spoke's `.md` definition instructs it to return a single fenced ` ```json `
   block conforming to `return.schema.json` — no prose outside the fence.
3. **The coordinator actually validates it** (`jsonschema.validate`, already a project
   dependency — don't skip this and eyeball the JSON instead). A return that fails to
   parse or fails validation is a `failure_type: malformed-return` — a real failure
   mode, not something to interpret charitably.
4. `status: success` requires `summary`, `files_changed`, `tests_run`,
   `contract_gaps` (empty array, not omitted, if none). `status: failure` requires
   `failure_type`, `attempted`, `partial_results`, `alternatives`. Never report success
   with an empty or stubbed deliverable.

---

## Routing table (dynamic selection)

Don't fan out on work that didn't need fanning out — the most common failure in this
architecture.

| Request shape | Invoke | Skip |
|---|---|---|
| Anything inside `apps/api/` | `api-agent` | web-agent |
| Anything inside `apps/web/` | `web-agent` | api-agent |
| Anything inside `packages/cfb-engine/` | the existing engine agents (see its own docs) | api-agent, web-agent |
| "Is the ranking / persona still correct?" | `validator` | — |
| "Is this done?" | `reviewer` + `validator` in parallel | — |
| Persona *voice/tone quality* judgment calls ("does this read as a good bar-stool guy?") | **coordinator directly** — this is a continuous, subjective, iterative judgment call, not a scoped implementation task (same reasoning as `cfb-strength-orchestrated`'s "algorithm disagrees with golden dataset" rule: some things don't decompose) | all spokes, until the coordinator has a specific, scoped prompt change to delegate |
| Typo, rename, one-line fix, config change | **nobody** — coordinator does it inline | all |
| A contract (shared type/schema) needs a new field | coordinator amends it, then re-delegates to every affected spoke | — |

---

## Error handling

All error handling routes through the coordinator. A subagent that fails, times out,
or returns a `malformed-return` is the coordinator's decision: retry with a rewritten
brief (append the specific validation error, mirroring retry-with-feedback), substitute
a different agent, or proceed with a named gap. Subagents never retry each other.
Silently suppressing a failure (treating an empty result as success) and aborting an
entire round because one spoke failed are both anti-patterns — a degraded round with a
named gap beats a dead round.
