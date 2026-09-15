import { test, expect } from '@playwright/test'

// Share-by-link smoke spec (issue #184). A share link holds the *question*;
// opening one fills in the form and re-asks the API with no click. Year 2005,
// Texas vs USC -- the golden comparison `compare.spec.ts` asks through the
// form -- with a "for" team, built with URLSearchParams in the same param
// order the app writes, so the link can be compared to what it copies.
//
// Since issue #198 the verdict opens in a modal over the form, so a friend
// opening the link on a phone sees it straight away.
const SHARE_SEARCH = new URLSearchParams({
  q: 'compare',
  sport: 'cfb',
  year: '2005',
  engine: 'keener',
  a: 'Texas',
  b: 'USC',
  for: 'Texas',
}).toString()

// Browser-side snippets, type-checked against the DOM lib by
// tsconfig.e2e.json (issue #226). Each is self-contained: Playwright ships a
// callback's source to the page, so it cannot close over anything here.
const readStoredUserTeam = () =>
  window.localStorage.getItem('myTeamIsBetter.userTeam')
const readClipboard = () => navigator.clipboard.readText()
const readWindowScrollY = () => window.scrollY
const readModalScrollTop = () => {
  const modal = document.querySelector('dialog[open]')
  if (modal === null) throw new Error('no open dialog')
  return modal.scrollTop
}
// Takes the clipboard branch: a desktop Chromium may otherwise offer a native
// share sheet that a headless run cannot dismiss.
const removeNativeShare = () => {
  Object.defineProperty(Navigator.prototype, 'share', {
    value: undefined,
    configurable: true,
  })
}

test('opening a share link answers its question in the verdict modal with no click and offers to share it', async ({
  page,
}) => {
  await page.goto(`/?${SHARE_SEARCH}`)

  const dialog = page.getByRole('dialog', { name: 'The verdict' })
  const verdict = dialog.getByRole('article')
  await expect(verdict).toBeVisible()
  await expect(verdict.getByText('Solid case, no notes.')).toBeVisible()
  // Exact <h4> team headings, as in `compare.spec.ts`.
  await expect(
    verdict.getByRole('heading', { name: 'Texas', exact: true }),
  ).toBeVisible()
  await expect(
    verdict.getByRole('heading', { name: 'USC', exact: true }),
  ).toBeVisible()
  await expect(
    verdict.getByRole('button', { name: 'Share this verdict' }),
  ).toBeVisible()
  // Focus is in the modal, on its close button.
  await expect(
    dialog.getByRole('button', { name: 'Close the verdict' }),
  ).toBeFocused()

  // The form behind it agrees with the question the link asked.
  await expect(page.getByLabel('What do you want to know?')).toHaveValue(
    'compare',
  )
  await expect(page.getByLabel('Year')).toHaveValue('2005')
  await expect(page.getByLabel('Team A', { exact: true })).toHaveValue('Texas')
  await expect(page.getByLabel('Team B', { exact: true })).toHaveValue('USC')
  await expect(
    page.getByLabel('Your team (optional)', { exact: true }),
  ).toHaveValue('Texas')
  // Someone else's link never becomes your saved team.
  expect(await page.evaluate(readStoredUserTeam)).toBeNull()
})

test('the Share button copies the link the verdict was opened with', async ({
  page,
  context,
}) => {
  await context.grantPermissions(['clipboard-read', 'clipboard-write'])
  await page.addInitScript(removeNativeShare)
  await page.goto(`/?${SHARE_SEARCH}`)

  const verdict = page
    .getByRole('dialog', { name: 'The verdict' })
    .getByRole('article')
  await verdict.getByRole('button', { name: 'Share this verdict' }).click()

  await expect(verdict.getByText('Link copied')).toBeVisible()
  const origin = new URL(page.url()).origin
  expect(await page.evaluate(readClipboard)).toBe(`${origin}/?${SHARE_SEARCH}`)
})

test('closing the verdict returns to the filled-in form, drops the share query, and a reload stays closed', async ({
  page,
}) => {
  await page.goto(`/?${SHARE_SEARCH}`)
  const dialog = page.getByRole('dialog', { name: 'The verdict' })
  await expect(dialog.getByText('Solid case, no notes.')).toBeVisible()

  await page.keyboard.press('Escape')

  await expect(dialog).toHaveCount(0)
  await expect(
    page.getByRole('button', { name: 'Get the verdict' }),
  ).toBeFocused()
  await expect.poll(() => new URL(page.url()).search).toBe('')
  await expect(page.getByLabel('Team A', { exact: true })).toHaveValue('Texas')
  await expect(page.getByLabel('Team B', { exact: true })).toHaveValue('USC')

  await page.reload()
  await expect(page.getByLabel('Year')).toBeVisible()
  await expect(page.getByLabel('What do you want to know?')).toHaveValue(
    'champion',
  )
  await expect(page.getByRole('dialog')).toHaveCount(0)
})

test('on a phone, a share link opens its verdict full screen with the first line in view, no scrolling, and a working close button', async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto(`/?${SHARE_SEARCH}`)

  const dialog = page.getByRole('dialog', { name: 'The verdict' })
  const verdict = dialog.getByRole('article')
  await expect(verdict).toBeVisible()
  // The verdict's first line, and the whole close button, with no scrolling.
  await expect(verdict.getByText('Solid case, no notes.')).toBeInViewport({
    ratio: 1,
  })
  const close = dialog.getByRole('button', { name: 'Close the verdict' })
  await expect(close).toBeInViewport({ ratio: 1 })
  expect(await page.evaluate(readWindowScrollY)).toBe(0)
  expect(await page.evaluate(readModalScrollTop)).toBe(0)

  // Full screen, and a 44x44 touch target.
  expect(await dialog.boundingBox()).toEqual({
    x: 0,
    y: 0,
    width: 390,
    height: 844,
  })
  const closeBox = await close.boundingBox()
  expect(closeBox?.width).toBeGreaterThanOrEqual(44)
  expect(closeBox?.height).toBeGreaterThanOrEqual(44)

  // A wheel over the modal never scrolls the page behind it, which is taller
  // than the screen, and the close button stays in view. (This fixture's
  // comparison fits a phone screen, so there is nothing to scroll inside the
  // modal here: `VerdictModal`'s LongSuccessScrolls story covers that.)
  await page.mouse.move(195, 600)
  await page.mouse.wheel(0, 1500)
  await expect(close).toBeInViewport({ ratio: 1 })
  expect(await page.evaluate(readWindowScrollY)).toBe(0)

  await close.click()

  await expect(dialog).toHaveCount(0)
  await expect(page.getByLabel('Team A', { exact: true })).toBeInViewport()
  await expect.poll(() => new URL(page.url()).search).toBe('')
})
