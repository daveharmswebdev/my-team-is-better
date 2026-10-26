"""The scored persona eval harness (issue #327; the QB narrator, model choice
and cost since #463, which includes #455).

Compares persona system-prompt variants, and narrator models, by number. For
each selected variant and each dataset case, `--samples N` times, it
narrates through production's own entry point (`api.persona.narrate.narrate`
for the team narrator, `api.persona.service.narrate_qb_comparison` for the
QB one) with a real `ClaudeNarrator` on the chosen model, grades the served
narration with code graders (`tests/fixtures/persona_eval.py`, #293, and for
the QB narrator `qb_graders.py`) and one model-grader call, prices every
call, and writes a side-by-side report. One run scores one narrator on one
model; compare models by running once per model and reading the reports
side by side. It is a dev tool, not a
test: nothing here matches `test_*.py`, so pytest never collects it, it never
runs in CI, and no score ever fails a merge. Its offline unit tests are
`tests/test_persona_eval_harness.py`, which do run in CI.

**Run it** from `apps/api`, with the key exported in the shell and nothing
else:

    env -u DATABASE_URL -u MY_TEAM_IS_BETTER_API_ENV_FILE PYTHONPATH=tests \\
        uv run python -m persona_eval_harness \\
        --variant baseline --variant degraded --samples 2 --max-calls 200 --out <dir>

    env -u DATABASE_URL -u MY_TEAM_IS_BETTER_API_ENV_FILE PYTHONPATH=tests \\
        uv run python -m persona_eval_harness --narrator qb --model claude-sonnet-5-5 \\
        --variant baseline --samples 3 --max-calls 400 --out <dir>

- `--narrator team|qb` (default `team`, everything below as before #463):
  `team` narrates spike #200's 11 team fact blocks (`dataset.py`); `qb`
  narrates the 8 QB-vs-QB blocks in `qb_dataset.py` (below).
- `--model ID` is the narrator model, one of `claude-haiku-4-5`,
  `claude-haiku-5-5` and `claude-sonnet-5-5` (the request profiles in
  `api.persona.claude_client`); the default is production's setting for that
  narrator (`api.config.TEAM_NARRATOR_MODEL` / `QB_NARRATOR_MODEL`). Any
  other id is refused.
- `--effort low|medium|high` overrides a 5.x model's effort (default
  `medium`). Refused with `claude-haiku-4-5`, which takes no effort.
- `--variant baseline` is production's `api.persona.prompt.build_system_prompt`
  (with `--narrator qb`, `api.persona.qb_prompt.build_qb_system_prompt`);
  `--variant degraded` is the shipped anti-vacuity control
  (`degraded_variant.py`: the prompt without its rules and worked examples),
  team only: it is refused with `--narrator qb`. Any other value is
  `name=path/to/variant.py`, a file exposing
  `build_system_prompt(user_team: str | None) -> str` (QB:
  `build_qb_system_prompt() -> str`), under any name but the reserved
  `baseline` and `degraded`. Repeat the flag; the first variant
  is the reference the report's spread check compares against.
- `--samples N` narrates every case N times per variant (default 1).
- `--case ID` (repeatable) restricts the dataset; `--dry-run` lists the ids.
- `--max-calls` is a hard cap on logical Claude calls, narrator and grader
  together: each narrator submit and each grader request counts once. The
  SDK's own automatic retries (up to 2 more HTTP requests per call, on a
  connection error, 408, 409, 429 or 5xx) happen inside a call and aren't
  counted, so the billed requests can reach three times the cap. The run is
  refused up front when the worst case (cases x N x variants x 3: two
  narrator calls and one grader call per narration) exceeds it, and it stops
  at the cap mid-run with a report marked partial.
- `--out DIR` receives `report.json`, `report.md` and `records.jsonl` (one
  line per narration: tool inputs, validator errors, served text, grader
  output). It is refused when it already holds a report.
- `--dry-run` builds and prints the narrator, model and effort, the dataset,
  the variants, the call estimate and a worst-case dollar estimate. It needs
  no key and makes no call.

**The QB dataset** (`qb_dataset.py`), every block a real one from
`tests/fixtures/qb_blocks.py`: a sweep (Warner vs McNair), a split
(`split_block()`), one cut-off career (McNabb vs Warner), the inconclusive
pair (Cunningham vs DeVito), the printed-equal pair (Wilson vs Lawrence), and
three production-shaped cases, `rescored_block` over Warner vs McNair with
live scores measured on 2026-10-25: `qb-brady-manning-split` (both measures
close), `qb-herbert-mayfield-clear` (both clear; the live miss where "not
close" was rejected twice and the fallback served) and
`qb-brady-flacco-decisive` (both decisive).

**The QB code graders** (`qb_graders.py`), each reported per case and per
variant as a pass rate: no hedge ("too close to call", "toss-up", ...), a
`year` claim in the accepted call, a `winner` claim for every measure with a
winner, and margin wording that fits the band under the founder's two-tier
rule (photo-finish words need a close measure, mild runaway words a clear or
decisive one, hard runaway words a decisive one; the word lists are one
table, `MARGIN_WORDING`). A served fallback is N/A on the last three.

**Cost** (`cost.py`). Each narrator call's and grader call's token usage is
in records.jsonl with the narration's dollars (narrator only, and narrator
plus grader), and the report gives the mean dollars per narration per
variant, from a price table per model (cache writes 1.25x input, cache reads
0.1x). A call with no usage (a fake narrator) leaves that narration
unpriced, never free. The `--dry-run` estimate assumes every call spends its
whole `max_tokens`, so a real run costs a small fraction of it.

**Exit codes.** 0 a complete, error-free run or a dry run; 2 refused; 3 a
run the cap stopped part-way; 4 any narrator or grader transport error
(it takes precedence over 3). The report is written in cases 3 and 4.

**Outcomes and transport errors.** Each narration is served `first`,
`retry`, `fallback` or `untraceable` (as `fixtures.persona_eval` judges it),
or `error`: a narrator call raised a transport error
(`anthropic.APIStatusError` or `APIConnectionError`, after the SDK's own
retries) and production served the fallback because of it. An `error`
narration is never graded, is left out of every rate, mean and sample round,
and is counted per variant and per case (`narrator_errors`). A grader
transport error leaves that narration ungraded and is counted too
(`grader_errors`). Either one puts a TRANSPORT ERRORS line at the top of
report.md, prints a WARNING on stderr and exits 4: the numbers may reflect an
outage rather than the prompt, so re-run before reading them.

**Voice score.** The model grader (`grader.py`, `GRADER_PROMPT_VERSION`
`grader-v2`) grades every served text, fallbacks included, so the report
gives two means: over all graded narrations, and over the narrator-served
ones only. A gap in the second is a voice gap; a gap only in the first may be
a fallback-count gap.

**Secrets rule** (spoke-protocol). A live run makes real narrator calls on
the chosen model (`claude-haiku-4-5`, `claude-haiku-5-5` or
`claude-sonnet-5-5`) and `claude-opus-5` grader calls, so it costs money;
run it only from a worktree with no `apps/api/.env`. The harness enforces
that before it imports anything that could load `.env` or reach Postgres
(`api.config` loads `.env` at import): it refuses to start when
`apps/api/.env` exists, when `DATABASE_URL` or
`MY_TEAM_IS_BETTER_API_ENV_FILE` is set (even to an empty string), and, for
a live run, when `ANTHROPIC_API_KEY` is unset. Nothing here opens Postgres:
the dataset reads the committed CFB sqlite fixture and a throwaway NFL sqlite
db built in a temporary directory.

**Known limits.**

- A variant swaps the system prompt only, and a run uses one narrator
  model. There are no tool-schema or validator variants: the tool schema and its description strings
  (`api.persona.claims.tool_schema`), the validator, the retry feedback and
  the user turn are production's in every variant, so a prompt change that
  only works with a schema or validator change can't be scored here as a
  prompt-only variant.
- `user_team` is `None` for every case, as the routes default it; the
  allegiance clauses are not exercised.
- The model grader is one fixed model (`claude-opus-5`) with a fixed rubric
  (`GRADER_PROMPT_VERSION`), the same for both narrators; scores are
  comparable only between reports that carry the same grader model and
  grader prompt version. No server-side
  model fallback is configured, on purpose: a different grader would make
  scores incomparable.
- A difference smaller than the run-to-run spread (the min-max across sample
  rounds the report prints) is noise, not a finding. With `--samples 1` there
  is no spread to compare against.
"""
