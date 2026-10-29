## Why
apps/web faked the API three ways across 17 files (#221, which named 6 when it was filed):
- 7 test files used `vi.mock` on the client module;
- 4 used `vi.stubGlobal('fetch')`;

## What changed
- **MSW, one set of typed handlers.** `src/mocks/handlers.ts` has one builder per client function.

## Verification (re-run by the coordinator, not only the spoke)
- `npm run test`: 1755 passed.

## Delegation record
contract_gaps: none
brief_defects: none
Findings filed: none

<details><summary>Validated returns and review rounds</summary>

web-agent r1
```json
{
 "status": "success",
 "agent": "web-agent",
 "summary": "Round 2 of #221 fixes all three blocking findings and takes the nits.",
 "findings": []
}
```

</details>

Closes #221

🤖 Generated with [Claude Code](https://claude.com/claude-code)
