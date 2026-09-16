"""The scored persona eval harness (issue #327).

Compares persona system-prompt variants by number. For each selected variant
and each dataset case, `--samples N` times, it narrates through production
`api.persona.narrate.narrate` with a real `ClaudeNarrator`, grades the served
narration with code graders (`tests/fixtures/persona_eval.py`, #293) and one
model-grader call, and writes a side-by-side report. It is a dev tool, not a
test: nothing here matches `test_*.py`, so pytest never collects it, it never
runs in CI, and no score ever fails a merge. Its offline unit tests are
`tests/test_persona_eval_harness.py`, which do run in CI.

**Run it** from `apps/api`, with the key exported in the shell and nothing
else:

    env -u DATABASE_URL -u MY_TEAM_IS_BETTER_API_ENV_FILE PYTHONPATH=tests \\
        uv run python -m persona_eval_harness \\
        --variant baseline --variant degraded --samples 2 --max-calls 200 --out <dir>

- `--variant baseline` is production's `api.persona.prompt.build_system_prompt`;
  `--variant degraded` is the shipped anti-vacuity control
  (`degraded_variant.py`: the prompt without its rules and worked examples);
  any other value is `name=path/to/variant.py`, a file exposing
  `build_system_prompt(user_team: str | None) -> str`. Repeat the flag; the
  first variant is the reference the report's spread check compares against.
- `--samples N` narrates every case N times per variant (default 1).
- `--case ID` (repeatable) restricts the dataset; `--dry-run` lists the ids.
- `--max-calls` is a hard cap on every Claude call, narrator and grader
  together. The run is refused up front when the worst case (cases x N x
  variants x 3: two narrator calls and one grader call per narration) exceeds
  it, and it stops at the cap mid-run with a report marked partial.
- `--out DIR` receives `report.json`, `report.md` and `records.jsonl` (one
  line per narration: tool inputs, validator errors, served text, grader
  output). It is refused when it already holds a report.
- `--dry-run` builds and prints the dataset, the variants and the call
  estimate. It needs no key and makes no call.

**Secrets rule** (spoke-protocol). A live run makes real `claude-haiku-4-5`
and `claude-opus-5` calls, so it costs money; run it only from a worktree
with no `apps/api/.env`. The harness enforces that before it imports anything
that could load `.env` or reach Postgres (`api.config` loads `.env` at
import): it refuses to start when `apps/api/.env` exists, when `DATABASE_URL`
or `MY_TEAM_IS_BETTER_API_ENV_FILE` is set (even to an empty string), and, for
a live run, when `ANTHROPIC_API_KEY` is unset. Nothing here opens Postgres:
the dataset reads the committed CFB sqlite fixture and a throwaway NFL sqlite
db built in a temporary directory.

**Known limits.**

- A variant swaps the system prompt only. The tool schema and its description
  strings (`api.persona.claims.tool_schema`), the validator, the retry
  feedback and the user turn are production's in every variant, so a prompt
  change that only works with a schema or validator change can't be scored
  here as a prompt-only variant.
- `user_team` is `None` for every case, as the routes default it; the
  allegiance clauses are not exercised.
- The model grader is one fixed model (`claude-opus-5`) with a fixed rubric
  (`GRADER_PROMPT_VERSION`); scores are comparable only between reports that
  carry the same grader model and grader prompt version. No server-side
  model fallback is configured, on purpose: a different grader would make
  scores incomparable.
- A difference smaller than the run-to-run spread (the min-max across sample
  rounds the report prints) is noise, not a finding. With `--samples 1` there
  is no spread to compare against.
"""
