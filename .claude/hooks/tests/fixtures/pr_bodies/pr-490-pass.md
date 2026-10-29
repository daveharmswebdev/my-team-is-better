## Why
`api.repositories.teams.list_all_team_names` has had no production caller since #291 moved grounding onto the typed-claim validator (which reads `list_team_records`).

## What changed
- Deleted `list_all_team_names`. Every docstring and comment now says what grounding reads.
- No behaviour, route, `models.py` or `list_team_records` change; no `PROMPT_VERSION` bump needed.

## Verification (re-run by the coordinator, not only the spoke)
- `uv run pytest -q` (apps/api, worktree without `.env`): 2736 passed, 36 skipped (after the nit commit too)
- `mypy --strict src/api tests`: clean (152 files); `ruff check` and `ruff format --check`: clean

## Delegation record
contract_gaps: none
brief_defects: none
Findings filed: none (2 reviewer nits, fixed in this PR)

<details><summary>Validated returns</summary>

api-agent r1: status success, head 00f7743, 12 files.
</details>

Closes #336

🤖 Generated with [Claude Code](https://claude.com/claude-code)
