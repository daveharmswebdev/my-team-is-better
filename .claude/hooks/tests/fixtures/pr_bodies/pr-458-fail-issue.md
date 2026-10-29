## Why
`src/test/eslintTypeAware.test.ts` (from #222, PR #453) failed on PR #456's CI: `rejects a floating promise` hit Vitest's 5 s default (7026 ms).

## What changed
- The suite's `describe` gets `{ timeout: 30_000 }`, with a comment saying why.

## Verification
From `apps/web`: `npx vitest run src/test/eslintTypeAware.test.ts` 13 passed · `npm run lint` clean.

Coordinator inline fix (routing table: a one-line fix), no delegation.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
