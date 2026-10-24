import type { Request } from '@playwright/test'
import { test, expect } from './fixtures.ts'

// Issue #242: index.html's Google Fonts stylesheet is a render-blocking
// request, so the page's `load` event (what `page.goto` waits for) waits on
// fonts.googleapis.com. Under --repeat-each load that request sometimes got
// no answer for 29.3s (net::ERR_TIMED_OUT), and every spec navigating at that
// moment failed in `page.goto`. The harness now answers every request for a
// host other than this run's own servers itself, so a page load in e2e never
// waits on the internet, and this spec proves it.

function isLocal(url: string): boolean {
  const { hostname } = new URL(url)
  return hostname === 'localhost' || hostname === '127.0.0.1'
}

test('every third-party request is answered by the harness, never the internet', async ({
  page,
}) => {
  const external: Request[] = []
  page.on('request', (request) => {
    if (!isLocal(request.url())) {
      external.push(request)
    }
  })

  await page.goto('/')

  // index.html links Google Fonts today; if that link ever goes, this spec
  // still holds (there is nothing external to answer), so it doesn't pin it.
  for (const request of external) {
    const response = await request.response()
    expect(
      response?.headers()['x-e2e-harness'],
      `${request.url()} reached the network instead of the e2e harness`,
    ).toBe('offline')
  }
})
