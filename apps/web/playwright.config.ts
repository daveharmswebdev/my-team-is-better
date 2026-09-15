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

/**
 * Ports (issue #226). Both come from the environment, with the defaults CI
 * relies on (CI sets neither), and everything below -- `baseURL`, both
 * `webServer` URLs, uvicorn's and `vite preview`'s `--port`, the API's CORS
 * allow-list and the API base baked into the built app -- derives from these
 * two, so nothing else in this file names a port. Several coordinator
 * worktrees run at once here, and each needs its own pair. To run a second
 * suite alongside one already on the defaults:
 *
 *   E2E_API_PORT=8010 E2E_WEB_PORT=4183 npx playwright test
 *
 * `reuseExistingServer` is off unconditionally: with several worktrees
 * running, something already listening on :4173 is far more likely to be a
 * stranger's preview server than this checkout's, and borrowing it means
 * ERR_CONNECTION_REFUSED when it goes away mid-run (291 of 300 runs on #197).
 * A busy port fails fast with Playwright's port-in-use error instead, and the
 * fix is the line above.
 */
function portFromEnv(name: string, fallback: number): number {
  const raw = process.env[name]
  if (raw === undefined || raw === '') {
    return fallback
  }
  if (!/^\d+$/.test(raw)) {
    throw new Error(`${name} must be a port number, got ${JSON.stringify(raw)}`)
  }
  return Number(raw)
}

const API_PORT = portFromEnv('E2E_API_PORT', 8000)
const WEB_PORT = portFromEnv('E2E_WEB_PORT', 4173)
const API_ORIGIN = `http://localhost:${API_PORT}`
const WEB_ORIGIN = `http://localhost:${WEB_PORT}`

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
    baseURL: WEB_ORIGIN,
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
      command: `cd ../api && APP_TEST_MODE=1 CORS_ALLOWED_ORIGINS=${WEB_ORIGIN} CFB_DB_PATH=tests/fixtures/cfb_verdict_fixture.sqlite3 uv run uvicorn api.main:app --port ${API_PORT}`,
      url: `${API_ORIGIN}/health`,
      reuseExistingServer: false,
    },
    {
      // `vite preview` (already available via the existing `preview` npm
      // script) serves the production build -- chosen over adding a separate
      // static-file-server devDependency since it needs none.
      // `src/lib/api/client.ts` reads `VITE_API_BASE_URL` at build time and
      // only defaults to :8000, so the build gets this run's API origin.
      // `--strictPort` keeps `vite preview` from quietly moving to the next
      // free port if the one it was given is taken.
      command: `VITE_API_BASE_URL=${API_ORIGIN} npm run build && npm run preview -- --port ${WEB_PORT} --strictPort`,
      url: WEB_ORIGIN,
      reuseExistingServer: false,
    },
  ],
})
