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
  // Serial, not `fullyParallel` -- concurrent requests against the
  // `APP_TEST_MODE=1` FastAPI server reproducibly hit a real thread-safety
  // bug in `apps/api` (`sqlite3.ProgrammingError: SQLite objects created in
  // a thread can only be used in that same thread`, from `get_db_conn`'s
  // connection crossing FastAPI's per-request threadpool threads under
  // concurrent load). That bug is outside this task's scope (`apps/api`) --
  // reported as a contract gap -- but this e2e layer serializes its own
  // three specs in the meantime so it is green and stable rather than
  // reproducing a known, already-reported issue on every run.
  fullyParallel: false,
  workers: 1,
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
      // fixture db (2001/2005/2013 golden data). `APP_TEST_MODE=1` makes
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
