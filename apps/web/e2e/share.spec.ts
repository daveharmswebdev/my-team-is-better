import { test, expect } from '@playwright/test'

// Share-by-link smoke spec (issue #184). A share link holds the *question*;
// opening one fills in the form and re-asks the API with no click. Year 2005,
// Texas vs USC -- the golden comparison `compare.spec.ts` asks through the
// form -- with a "for" team, built with URLSearchParams in the same param
// order the app writes, so the link can be compared to what it copies.
const SHARE_SEARCH = new URLSearchParams({
  q: 'compare',
  sport: 'cfb',
  year: '2005',
  engine: 'keener',
  a: 'Texas',
  b: 'USC',
  for: 'Texas',
}).toString()

// Browser-side snippets are passed as strings: this directory type-checks
// against Node's globals, which have no `window` and a `Navigator` with no
// `clipboard`.
const READ_STORED_USER_TEAM =
  "window.localStorage.getItem('myTeamIsBetter.userTeam')"
const READ_CLIPBOARD = 'navigator.clipboard.readText()'
// Takes the clipboard branch: a desktop Chromium may otherwise offer a native
// share sheet that a headless run cannot dismiss.
const REMOVE_NATIVE_SHARE =
  "Object.defineProperty(Navigator.prototype, 'share', { value: undefined, configurable: true })"

test('opening a share link answers its question with no click and offers to share it', async ({
  page,
}) => {
  await page.goto(`/?${SHARE_SEARCH}`)

  const verdict = page.getByRole('article')
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

  // The visible form agrees with the question the link asked.
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
  expect(await page.evaluate(READ_STORED_USER_TEAM)).toBeNull()
})

test('the Share button copies the link the verdict was opened with', async ({
  page,
  context,
}) => {
  await context.grantPermissions(['clipboard-read', 'clipboard-write'])
  await page.addInitScript({ content: REMOVE_NATIVE_SHARE })
  await page.goto(`/?${SHARE_SEARCH}`)

  const verdict = page.getByRole('article')
  await verdict.getByRole('button', { name: 'Share this verdict' }).click()

  await expect(verdict.getByText('Link copied')).toBeVisible()
  const origin = new URL(page.url()).origin
  expect(await page.evaluate(READ_CLIPBOARD)).toBe(`${origin}/?${SHARE_SEARCH}`)
})
