---
paths:
  - "apps/web/**"
---

# apps/web: the exact checks

From `apps/web`, the same order as the `apps-web` CI job:

`npm run lint` · `npx tsc -b` · `npm run dep-cruise` · `npm run test` · `npm run build` ·
`npm run build-storybook` · `npm run test-storybook` (needs
`npx playwright install chromium` once) · plus `npm run format:check`, which CI doesn't
run yet (#116), so run it yourself.

- `npx tsc -b`, never a plain `tsc --noEmit`: the solution tsconfig has `"files": []`, so
  a root `--noEmit` checks zero files and passes on real errors.
- Every component ships a Vitest + React Testing Library test **and** a Storybook story;
  every story runs under the a11y addon in CI. Don't opt a story out of a11y to pass.
- `dependency-cruiser` is the boundary (components never import pages). Needing to cross
  it is a `contract-insufficient` finding, not an `eslint-disable` or a moved import.
- No `any` without a comment saying why it's unavoidable.
- A local `npx playwright test` leaves `test-results/` and `playwright-report/` behind
  (#160): delete them before you finish.
