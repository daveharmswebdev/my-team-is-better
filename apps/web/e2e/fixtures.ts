import { test as base, expect } from '@playwright/test'
import type { Route } from '@playwright/test'

/**
 * The `test` every e2e spec imports (issue #242). It is Playwright's own
 * `test`, except that each browser context answers requests for any host
 * other than this run's own servers itself, so no e2e page load waits on the
 * internet.
 *
 * Why: index.html links a Google Fonts stylesheet, a render-blocking request,
 * so the `load` event `page.goto` waits for also waits on fonts.googleapis.com.
 * Under `--repeat-each` load that request sometimes got no answer for 29.3s
 * (`net::ERR_TIMED_OUT` in the trace) while the preview server answered its
 * own assets in under 40ms, and every spec navigating at that moment failed
 * in `page.goto` -- the bunched stalls #242 describes. The app falls back to
 * its local font stack, which is what a visitor whose Google Fonts request
 * fails sees too.
 *
 * ESLint stops a spec importing `test` from `@playwright/test` directly, so a
 * new spec can't quietly skip this.
 */

const HARNESS_HEADER = { 'x-e2e-harness': 'offline' }

function isOwnServer(url: URL): boolean {
  return url.hostname === 'localhost' || url.hostname === '127.0.0.1'
}

async function answerOffline(route: Route): Promise<void> {
  const isStylesheet = route.request().resourceType() === 'stylesheet'
  await route.fulfill({
    status: 200,
    headers: HARNESS_HEADER,
    contentType: isStylesheet ? 'text/css' : 'text/plain',
    body: '',
  })
}

export const test = base.extend({
  // Playwright calls the second parameter `use`; it is named `provide` here
  // because react-hooks/rules-of-hooks reads any `use(...)` call as a hook.
  context: async ({ context }, provide) => {
    await context.route((url) => !isOwnServer(url), answerOffline)
    await provide(context)
  },
})

export { expect }
