import type { Request } from '@playwright/test'
import { test, expect } from './fixtures.ts'

// Issue #242: index.html's Google Fonts stylesheet was a render-blocking
// request, so the page's `load` event (what `page.goto` waits for) waited on
// fonts.googleapis.com. Under --repeat-each load that request sometimes got
// no answer for 29.3s (net::ERR_TIMED_OUT), and every spec navigating at that
// moment failed in `page.goto`. The harness answers every request for a host
// other than this run's own servers itself, so a page load in e2e never waits
// on the internet, and the first spec proves it.
//
// Issue #405: the fonts are now self-hosted, so the live site doesn't wait on
// a third party either. The second spec proves a page load asks no other host
// for anything, and that the typefaces really load from this origin.

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

  for (const request of external) {
    const response = await request.response()
    expect(
      response?.headers()['x-e2e-harness'],
      `${request.url()} reached the network instead of the e2e harness`,
    ).toBe('offline')
  }
})

test('the home page makes no third-party request and its fonts load from this origin', async ({
  page,
}) => {
  const external: string[] = []
  page.on('request', (request) => {
    if (!isLocal(request.url())) {
      external.push(request.url())
    }
  })

  await page.goto('/')
  await expect(
    page.getByRole('heading', { level: 1, name: 'My Team Is Better' }),
  ).toBeVisible()

  const fonts = await page.evaluate(async () => {
    await document.fonts.ready
    // `document.fonts.check` is also true for a family with no @font-face at
    // all (there is nothing to wait for), so also require a face of each
    // family that really loaded.
    const loaded = new Set<string>()
    document.fonts.forEach((face) => {
      if (face.status === 'loaded') loaded.add(face.family.replace(/"/g, ''))
    })
    return {
      check: {
        Anton: document.fonts.check('400 1em Anton'),
        Barlow: document.fonts.check('400 1em Barlow'),
      },
      loaded: [...loaded].sort(),
    }
  })

  expect(external, 'requests to hosts other than localhost').toEqual([])
  expect(fonts.check).toEqual({ Anton: true, Barlow: true })
  expect(fonts.loaded).toEqual(expect.arrayContaining(['Anton', 'Barlow']))
})
