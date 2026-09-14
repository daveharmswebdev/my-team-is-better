import { defineConfig, devices } from '@playwright/test'

/**
 * Browser-level e2e layer (issue #39) -- distinct from and additive to the
 * Vitest + React Testing Library component tests under `src/**\/*.test.tsx`,
 * which keep running exactly as they do today (see `vite.config.ts`'s
 * `test.exclude`, which keeps this directory out of Vitest's own run).
 *
 * Chromium only for v1 -- no cross-browser matrix yet (issue #39's stated
 * initial scope).
 */
export default defineConfig({
  testDir: './e2e',
  // Parallel again as of #44/#99. This was previously pinned to
  // `fullyParallel: false, workers: 1` because concurrent requests against
  // the `APP_TEST_MODE=1` FastAPI server reproducibly hit a real
  // thread-safety bug in `apps/api` (`sqlite3.ProgrammingError: SQLite
  // objects created in a thread can only be used in that same thread`, from
  // `get_db_conn`'s connection crossing FastAPI's per-request threadpool
  // threads under concurrent load). #99 fixed that at the source, so the
  // workaround is not only unnecessary, it was actively harmful: serializing
  // this layer removed the only cross-app concurrency the repo has, which
  // means nothing in CI could have caught a regression of #44 -- a bug
  // measured at 16 of 18 concurrent requests returning HTTP 500. Keeping
  // these specs parallel is what makes this layer a real guard against it
  // coming back, so do not re-serialize it to paper over flakiness: a
  // concurrency failure here is a signal, not noise.
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  reporter: 'html',
  use: {
    baseURL: 'http://localhost:4173',
    trace: 'on-first-retry',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
  webServer: [
    {
      // Boots the real FastAPI app in test mode against the committed
      // fixture db (the seven PRD golden years since #110, with real team
      // mascots, which is why `e2e/pickTeam.ts` allows a ` · <mascot>`
      // suffix on suggestion names). `APP_TEST_MODE=1` makes
      // `api.deps`'s `get_narration_cache`/`get_narrator` return the same
      // in-memory cache / stub narrator pytest already trusts, so this
      // e2e run needs neither a live Postgres instance nor a real
      // `ANTHROPIC_API_KEY` (see apps/api's own test-mode seam, issue #39's
      // groundwork).
      command:
        'cd ../api && APP_TEST_MODE=1 CORS_ALLOWED_ORIGINS=http://localhost:4173 CFB_DB_PATH=tests/fixtures/cfb_verdict_fixture.sqlite3 uv run uvicorn api.main:app --port 8000',
      url: 'http://localhost:8000/health',
      reuseExistingServer: !process.env.CI,
    },
    {
      // `vite preview` (already available via the existing `preview` npm
      // script) serves the production build on a fixed port -- chosen over
      // adding a separate static-file-server devDependency since it needs
      // none. `src/lib/api/client.ts`'s `VITE_API_BASE_URL` already
      // defaults to `http://localhost:8000` when unset, so no env override
      // is needed here for the built app to reach the API entry above.
      command: 'npm run build && npm run preview -- --port 4173',
      url: 'http://localhost:4173',
      reuseExistingServer: !process.env.CI,
    },
  ],
})
