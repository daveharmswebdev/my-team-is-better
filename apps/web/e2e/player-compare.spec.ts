import { test, expect } from '@playwright/test'
import type { Locator, Page } from '@playwright/test'

// Issue #301: the NFL player comparison, end to end against the real API on
// the committed fixture db (NFL 1999 + 2023). Every number here was measured
// on that fixture: Kurt Warner's 4,044 regular-season yards to Steve McNair's
// 2,179, McNair's 4 playoff games to Warner's 3, and their two games as
// opposing starters, 1999 week 8 (Titans 24, Rams 21) and week 21 (Rams 23,
// Titans 16).
//
// Since issue #310 every answer to a committed pair opens in a modal over the
// form, the way #198 did for team verdicts, so a shared link opens on the
// comparison instead of on the form. The form behind it is inert while it is
// open, so changing a pick starts by closing the comparison.

const WARNER = '2044124519'
const MCNAIR = '2385180619'
const MANNING = '2153701690'

/** The share link this page writes, and the one the specs below open. */
const WARNER_VS_MCNAIR_SEARCH = `a=${WARNER}&b=${MCNAIR}`

// Browser-side snippets, type-checked against the DOM lib by
// tsconfig.e2e.json (issue #226). Each is self-contained: Playwright ships a
// callback's source to the page, so it cannot close over anything here.
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

/** A totals row's two value cells, player A's first. */
function valueCells(table: Locator, label: string): Locator {
  return table
    .locator('tbody tr')
    .filter({
      has: table.page().getByRole('rowheader', { name: label, exact: true }),
    })
    .getByRole('cell')
}

/** The comparison modal, by the two players it names. */
function comparisonModal(page: Page, title: string): Locator {
  return page.getByRole('dialog', { name: title })
}

const closeButton = (page: Page) =>
  page.getByRole('button', { name: 'Close the comparison' })

test("from Kurt Warner's career, Compare and Player B's typeahead put Kurt Warner next to Steve McNair", async ({
  page,
}) => {
  await page.goto(`/nfl/players/${WARNER}`)
  await page
    .getByRole('link', { name: 'Compare Kurt Warner with another player' })
    .click()

  await expect(page).toHaveURL(new RegExp(`/nfl/compare\\?a=${WARNER}$`))
  const playerA = page.getByLabel('Player A', { exact: true })
  const playerB = page.getByLabel('Player B', { exact: true })
  await expect(playerA).toHaveValue('Kurt Warner')
  // One player picked is a prompt, not an answer: nothing opens over the form.
  await expect(page.getByRole('dialog')).toHaveCount(0)

  await playerB.pressSequentially('McNair')
  await page.getByRole('option', { name: /Steve McNair/ }).click()
  await page.getByRole('button', { name: 'Compare', exact: true }).click()

  await expect(page).toHaveURL(
    new RegExp(`/nfl/compare\\?a=${WARNER}&b=${MCNAIR}$`),
  )
  await expect(playerB).toHaveValue('Steve McNair')

  const dialog = comparisonModal(page, 'Kurt Warner and Steve McNair')
  const regular = dialog.getByRole('table', {
    name: 'Kurt Warner and Steve McNair, regular season',
  })
  const yards = valueCells(regular, 'Passing yards')
  await expect(yards.nth(0)).toContainText('4,044')
  await expect(yards.nth(0)).toContainText('(larger number)')
  await expect(yards.nth(1)).toHaveText('2,179')

  const playoffs = dialog.getByRole('table', {
    name: 'Kurt Warner and Steve McNair, playoffs',
  })
  const games = valueCells(playoffs, 'Games')
  await expect(games.nth(0)).toHaveText('3')
  await expect(games.nth(1)).toContainText('(larger number)')

  const headToHead = dialog.getByRole('region', { name: 'Head to head' })
  const regularGames = headToHead.getByRole('list', {
    name: 'Regular-season games',
  })
  await expect(regularGames.getByRole('listitem')).toHaveCount(1)
  await expect(regularGames).toContainText(
    '1999 season · week 8 · Oct 31, 1999',
  )
  await expect(regularGames).toContainText(
    'St. Louis Rams 21, Tennessee Titans 24',
  )
  await expect(
    headToHead.getByText("Kurt Warner's record against Steve McNair: 0-1"),
  ).toBeVisible()

  const playoffGames = headToHead.getByRole('list', { name: 'Playoff games' })
  await expect(playoffGames.getByRole('listitem')).toHaveCount(1)
  await expect(playoffGames).toContainText(
    'St. Louis Rams 23, Tennessee Titans 16',
  )
  await expect(
    headToHead.getByText("Kurt Warner's record against Steve McNair: 1-0"),
  ).toBeVisible()

  // Where the numbers come from is credited with them, inside the modal.
  await expect(dialog.getByRole('link', { name: /nflverse/ })).toBeVisible()

  // A reload keeps both players, and reopens the comparison the URL names.
  await page.reload()
  await expect(playerA).toHaveValue('Kurt Warner')
  await expect(playerB).toHaveValue('Steve McNair')
  await expect(valueCells(regular, 'Passing yards').nth(0)).toContainText(
    '4,044',
  )

  // Back returns to Warner alone: no committed pair, so no modal.
  await page.goBack()
  await expect(page).toHaveURL(new RegExp(`/nfl/compare\\?a=${WARNER}$`))
  await expect(playerA).toHaveValue('Kurt Warner')
  await expect(playerB).toHaveValue('')
  await expect(regular).toHaveCount(0)
  await expect(page.getByRole('dialog')).toHaveCount(0)
})

// Issue #304: changing a pick and pressing Compare again compares the new
// pair. Measured on the fixture: Peyton Manning's 4,135 regular-season yards
// to Warner's 4,044, and no game with both as opposing starters.
test('changing Player B and pressing Compare again puts Kurt Warner next to Peyton Manning, and the clear control empties the field', async ({
  page,
}) => {
  await page.goto('/nfl/compare')
  const playerA = page.getByLabel('Player A', { exact: true })
  const playerB = page.getByLabel('Player B', { exact: true })
  const compare = page.getByRole('button', { name: 'Compare', exact: true })
  await expect(compare).toBeDisabled()

  await playerA.pressSequentially('Warner')
  await page.getByRole('option', { name: /Kurt Warner/ }).click()
  await playerB.pressSequentially('McNair')
  await page.getByRole('option', { name: /Steve McNair/ }).click()
  await compare.click()

  const warnerMcNair = page.getByRole('dialog').getByRole('table', {
    name: 'Kurt Warner and Steve McNair, regular season',
  })
  await expect(warnerMcNair).toBeVisible()

  // The modal owns the screen while it is open and the form behind it is
  // inert, so changing a pick starts by closing the comparison. Both fields
  // keep the pair that was compared, and the address bar drops ?a&b.
  await closeButton(page).click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect.poll(() => new URL(page.url()).search).toBe('')
  await expect(playerA).toHaveValue('Kurt Warner')
  await expect(playerB).toHaveValue('Steve McNair')

  // Type over Player B: the pick is gone until one is picked from the list.
  await playerB.selectText()
  await playerB.pressSequentially('Manning')
  await expect(compare).toBeDisabled()
  await expect(
    page.getByText('Pick each player from the list, then press Compare.'),
  ).toBeVisible()
  await page.getByRole('option', { name: /Peyton Manning/ }).click()
  await expect(playerB).toHaveValue('Peyton Manning')
  // Nothing is compared until Compare is pressed.
  await expect(page.getByRole('dialog')).toHaveCount(0)

  await compare.click()

  await expect(page).toHaveURL(
    new RegExp(`/nfl/compare\\?a=${WARNER}&b=${MANNING}$`),
  )
  const dialog = comparisonModal(page, 'Kurt Warner and Peyton Manning')
  const regular = dialog.getByRole('table', {
    name: 'Kurt Warner and Peyton Manning, regular season',
  })
  const yards = valueCells(regular, 'Passing yards')
  await expect(yards.nth(0)).toHaveText('4,044')
  await expect(yards.nth(1)).toContainText('4,135')
  await expect(yards.nth(1)).toContainText('(larger number)')
  await expect(warnerMcNair).toHaveCount(0)
  await expect(
    dialog
      .getByRole('region', { name: 'Head to head' })
      .getByText(
        'Kurt Warner and Peyton Manning never started against each other in the regular season.',
      ),
  ).toBeVisible()

  // Closing returns to the form, where the clear control still works.
  await closeButton(page).click()
  await page.getByRole('button', { name: 'Clear Player B' }).click()
  await expect(playerB).toHaveValue('')
  await expect(playerB).toBeFocused()
  await expect(compare).toBeDisabled()
})

test('the Primary nav reaches the compare page', async ({ page }) => {
  await page.goto('/')
  await page
    .getByRole('navigation', { name: 'Primary' })
    .getByRole('link', { name: 'Compare Players' })
    .click()

  await expect(page).toHaveURL(/\/nfl\/compare$/)
  await expect(
    page.getByRole('heading', { level: 1, name: 'Compare NFL players' }),
  ).toBeVisible()
  await expect(
    page.getByText('Pick two players to put their careers side by side.'),
  ).toBeVisible()
  await expect(page.getByRole('dialog')).toHaveCount(0)
})

test('an unknown player gets the narrator, not a status code', async ({
  page,
}) => {
  await page.goto(`/nfl/compare?a=${WARNER}&b=1`)

  // An answer to a committed pair, so it opens in the modal like any other.
  const alert = page.getByRole('dialog').getByRole('alert')
  await expect(alert).toContainText('Never heard of him, pal.')
  await expect(alert).not.toContainText('404')
  await expect(
    alert.getByRole('link', { name: /leaders board/ }),
  ).toHaveAttribute('href', '/nfl/leaders')
  // Nothing to share: there is no comparison.
  await expect(page.getByRole('button', { name: /^Share/ })).toHaveCount(0)
})

// Issue #310, modelled on `e2e/share.spec.ts`: a shared comparison link opens
// on the answer, offers to share itself, and closes back to the form.
test('a share link opens the comparison in a modal with no click, and offers to share it', async ({
  page,
}) => {
  await page.goto(`/nfl/compare?${WARNER_VS_MCNAIR_SEARCH}`)

  const dialog = comparisonModal(page, 'Kurt Warner and Steve McNair')
  await expect(
    dialog.getByRole('table', {
      name: 'Kurt Warner and Steve McNair, regular season',
    }),
  ).toBeVisible()
  await expect(
    dialog.getByRole('button', { name: 'Share this comparison' }),
  ).toBeVisible()
  // Focus is in the modal, on its close button.
  await expect(closeButton(page)).toBeFocused()

  // The form behind it holds the pair the link named.
  await expect(page.getByLabel('Player A', { exact: true })).toHaveValue(
    'Kurt Warner',
  )
  await expect(page.getByLabel('Player B', { exact: true })).toHaveValue(
    'Steve McNair',
  )
})

test('the Share button copies the link the comparison was opened with', async ({
  page,
  context,
}) => {
  await context.grantPermissions(['clipboard-read', 'clipboard-write'])
  await page.addInitScript(removeNativeShare)
  await page.goto(`/nfl/compare?${WARNER_VS_MCNAIR_SEARCH}`)

  const dialog = comparisonModal(page, 'Kurt Warner and Steve McNair')
  await dialog.getByRole('button', { name: 'Share this comparison' }).click()

  await expect(dialog.getByText('Link copied')).toBeVisible()
  const origin = new URL(page.url()).origin
  expect(await page.evaluate(readClipboard)).toBe(
    `${origin}/nfl/compare?${WARNER_VS_MCNAIR_SEARCH}`,
  )
})

test('closing the comparison returns to the filled-in form, drops the query, and a reload stays closed', async ({
  page,
}) => {
  await page.goto(`/nfl/compare?${WARNER_VS_MCNAIR_SEARCH}`)
  const dialog = comparisonModal(page, 'Kurt Warner and Steve McNair')
  await expect(dialog).toBeVisible()

  await page.keyboard.press('Escape')

  await expect(dialog).toHaveCount(0)
  await expect(
    page.getByRole('button', { name: 'Compare', exact: true }),
  ).toBeFocused()
  await expect.poll(() => new URL(page.url()).search).toBe('')
  // Both fields keep the pair, ready to compare again or to change.
  await expect(page.getByLabel('Player A', { exact: true })).toHaveValue(
    'Kurt Warner',
  )
  await expect(page.getByLabel('Player B', { exact: true })).toHaveValue(
    'Steve McNair',
  )

  await page.reload()
  await expect(
    page.getByRole('heading', { level: 1, name: 'Compare NFL players' }),
  ).toBeVisible()
  await expect(page.getByRole('dialog')).toHaveCount(0)
})

test('on a phone, a share link opens its comparison full screen with the first line in view, no scrolling, and a working close button', async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto(`/nfl/compare?${WARNER_VS_MCNAIR_SEARCH}`)

  const dialog = comparisonModal(page, 'Kurt Warner and Steve McNair')
  await expect(dialog).toBeVisible()
  // The comparison's first line -- the two players -- and the whole close
  // button, with no scrolling.
  await expect(
    dialog
      .getByRole('list', { name: 'Players compared' })
      .getByRole('link', { name: 'Kurt Warner' }),
  ).toBeInViewport({ ratio: 1 })
  const close = closeButton(page)
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

  // A wheel over the modal scrolls the comparison, never the page behind it,
  // and the sticky header keeps the close button in view.
  await page.mouse.move(195, 600)
  await page.mouse.wheel(0, 1500)
  await expect(close).toBeInViewport({ ratio: 1 })
  expect(await page.evaluate(readWindowScrollY)).toBe(0)

  await close.click()

  await expect(dialog).toHaveCount(0)
  await expect(page.getByLabel('Player A', { exact: true })).toBeInViewport()
  await expect.poll(() => new URL(page.url()).search).toBe('')
})
