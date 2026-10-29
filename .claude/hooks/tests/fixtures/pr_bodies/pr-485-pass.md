## Why
Step 1 of #484: career receiving EPA.

## What changed
- **Contract doc (coordinator):** `PLAYER_STAT_SPARSE_FIELDS` now says that a career receiving-EPA sum skips those NULL seasons like any blank.

## Verification (re-run by the coordinator, not only the spoke)
- `uv run pytest -q` (packages/cfb-engine): passed.

## Delegation record
contract_gaps: none
brief_defects: none
Findings filed: none

<details><summary>Validated returns and review rounds</summary>

ingest-agent r1: success, head 5414cce. Validated with `delegation.py validate-return`.
</details>

Refs #484 (step 1 of 2; the held board stays open)

🤖 Generated with [Claude Code](https://claude.com/claude-code)
