import { test, expect } from './fixtures.ts'
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

const PICK_TWO_COPY = 'Pick two players to put their careers side by side.'

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
  // Nothing is compared until Compare is pressed: no answer opens, and the
  // address bar names no pair, not even a lone ?b=<id> prompt (issue #325).
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect.poll(() => new URL(page.url()).search).toBe('')

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

// Issue #352: two receivers are compared on the stats they have. On the
// fixture, Tyreek Hill's 2023 is 1,799 receiving yards to CeeDee Lamb's
// 1,749; neither threw a pass or started at quarterback.
test('a link to two receivers compares their receiving, with no passing or record row', async ({
  page,
}) => {
  await page.goto('/nfl/compare?a=2052934910&b=2170634393')

  const dialog = comparisonModal(page, 'Tyreek Hill and CeeDee Lamb')
  const regular = dialog.getByRole('table', {
    name: 'Tyreek Hill and CeeDee Lamb, regular season',
  })
  const yards = valueCells(regular, 'Receiving yards')
  await expect(yards.nth(0)).toContainText('1,799')
  await expect(yards.nth(0)).toContainText('(larger number)')
  await expect(yards.nth(1)).toHaveText('1,749')
  for (const gone of ['Passing yards', 'Completions', 'Starter record']) {
    await expect(
      regular.getByRole('rowheader', { name: gone, exact: true }),
    ).toHaveCount(0)
  }
  // Head-to-head is for two quarterbacks only (#436).
  await expect(
    dialog.getByRole('region', { name: 'Head to head' }),
  ).toHaveCount(0)
  await expect(dialog.getByText(/started at quarterback/)).toHaveCount(0)
})

// Round 3 of #352: each player's columns are decided on his own stats.
// Since #433 only players of one position group compare, so the rule is
// shown with two running backs. On the fixture, Robert Farmer (RB, 1999)
// recorded nothing but solo tackles (8), which is defense for him; Marshall
// Faulk (RB, 1999) ran for 1,327 yards and made 1 solo tackle, which for him
// is not defense. Judged together, Faulk's rushing would hide Farmer's
// tackles-only line; judged one player at a time, Farmer's Solo tackles row
// still shows.
const FAULK = '2252790861'
const FARMER = '2039946310'

test("a running back next to a tackles-only running back keeps the tackles-only player's Solo tackles row", async ({
  page,
}) => {
  await page.goto(`/nfl/compare?a=${FAULK}&b=${FARMER}`)

  const dialog = comparisonModal(page, 'Marshall Faulk and Robert Farmer')
  const regular = dialog.getByRole('table', {
    name: 'Marshall Faulk and Robert Farmer, regular season',
  })
  const tackles = valueCells(regular, 'Solo tackles')
  await expect(tackles.nth(0)).toHaveText('1')
  await expect(tackles.nth(1)).toContainText('8')
  await expect(tackles.nth(1)).toContainText('(larger number)')
  await expect(valueCells(regular, 'Rushing yards').nth(0)).toContainText(
    '1,327',
  )
  // Two backs: no head-to-head section (#436).
  await expect(
    dialog.getByRole('region', { name: 'Head to head' }),
  ).toHaveCount(0)
})

// Issue #436 (epic #372, step 3): a link to a quarterback and a safety (Kurt
// Warner, Zayne Anderson) is refused, never shown. The API's 400 names the
// groups (QB, none); the safety has none, so the narrator names him by his
// position. Kurt Warner stays as Player A; Player B is emptied and ready for
// another quarterback; the address bar names no pair (#325).
test('a link to players from different position groups is refused, keeping Player A', async ({
  page,
}) => {
  await page.goto(`/nfl/compare?a=${WARNER}&b=2071342796`)

  const alert = page.getByRole('alert')
  await expect(alert).toHaveText(
    "A quarterback and a safety? That's apples and footballs, pal. Pick another quarterback.",
  )
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(page.getByRole('table')).toHaveCount(0)
  await expect(page.locator('main')).not.toContainText('400')
  await expect(page.getByRole('button', { name: /^Share/ })).toHaveCount(0)
  await expect(page).toHaveURL(new RegExp(`/nfl/compare\\?a=${WARNER}$`))

  const playerA = page.getByLabel('Player A', { exact: true })
  const playerB = page.getByLabel('Player B', { exact: true })
  await expect(playerA).toHaveValue('Kurt Warner')
  await expect(playerB).toHaveValue('')
  await expect(playerB).toBeEnabled()
  await expect(playerB).toBeFocused()
  await expect(
    page.getByText(
      'Comparing quarterbacks. Player B has to be a quarterback too.',
    ),
  ).toBeVisible()

  // A new quarterback for Player B: the refusal goes, Compare is on.
  await playerB.pressSequentially('McNair')
  await page.getByRole('option', { name: /Steve McNair/ }).click()
  await expect(page.getByRole('alert')).toHaveCount(0)
  await expect(
    page.getByRole('button', { name: 'Compare', exact: true }),
  ).toBeEnabled()
})

// Issue #436: Player B waits for Player A, then searches only Player A's
// group. On the fixture, Eddie George is a 1999 running back: with him as
// Player A, "warner" finds nobody for Player B, and "faulk" finds Marshall
// Faulk (and Kevin Faulk, also a back).
test("a Player A pick restricts Player B's typeahead to his group", async ({
  page,
}) => {
  await page.goto('/nfl/compare')
  const playerA = page.getByLabel('Player A', { exact: true })
  const playerB = page.getByLabel('Player B', { exact: true })
  await expect(playerB).toBeDisabled()

  await playerA.pressSequentially('George')
  await page.getByRole('option', { name: /Eddie George/ }).click()

  await expect(playerB).toBeEnabled()
  await expect(
    page.getByText(
      'Comparing running backs. Player B has to be a running back too.',
    ),
  ).toBeVisible()

  await playerB.pressSequentially('warner')
  await expect(page.getByText('Nobody by that name.')).toBeVisible()
  await expect(page.getByRole('option')).toHaveCount(0)

  await playerB.fill('')
  await playerB.pressSequentially('faulk')
  await expect(
    page.getByRole('option', { name: /Marshall Faulk/ }),
  ).toBeVisible()
  for (const option of await page.getByRole('option').all()) {
    await expect(option).toContainText('RB')
  }

  // Clearing Player A clears Player B, and Player B waits again.
  await page.getByRole('option', { name: /Marshall Faulk/ }).click()
  await page.getByRole('button', { name: 'Clear Player A' }).click()
  await expect(playerB).toHaveValue('')
  await expect(playerB).toBeDisabled()
})

// Issue #436: a kicker has no group, so there is nobody to compare him with
// yet. Jeff Wilkins kicked for the 1999 Rams on the fixture.
test('a kicker as Player A gets the uncomparable line, and Player B stays disabled', async ({
  page,
}) => {
  await page.goto('/nfl/compare')
  const playerA = page.getByLabel('Player A', { exact: true })
  await playerA.pressSequentially('Wilkins')
  await page.getByRole('option', { name: /Jeff Wilkins/ }).click()

  await expect(
    page.getByText(
      "Can't stack up kickers yet. Quarterbacks, running backs, receivers and tight ends only, for now.",
    ),
  ).toBeVisible()
  await expect(page.getByLabel('Player B', { exact: true })).toBeDisabled()
  await expect(
    page.getByRole('button', { name: 'Compare', exact: true }),
  ).toBeDisabled()
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
  // The form holds two players, so it doesn't ask for two (issue #324).
  await expect(page.getByText(PICK_TWO_COPY)).toHaveCount(0)

  await page.reload()
  await expect(
    page.getByRole('heading', { level: 1, name: 'Compare NFL players' }),
  ).toBeVisible()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  // A reload re-seeds from the empty URL: nobody held, so pick two.
  await expect(page.getByText(PICK_TWO_COPY)).toBeVisible()
})

// Issue #308: a link whose comparison fails keeps its pair. The fields say
// which players the link named, closing puts focus on an enabled Compare,
// and pressing it asks for the same pair again, with no reload. The retry
// is held until the test has seen it loading: the first failure's line must
// not stand in for the retry's answer while it is out (round 2).
test('a link whose comparison failed can be asked again after closing it', async ({
  page,
}) => {
  let failNext = true
  let releaseRetry: () => void = () => {}
  const retryReleased = new Promise<void>((resolve) => {
    releaseRetry = resolve
  })
  await page.route('**/api/players/compare**', async (route) => {
    if (failNext) {
      failNext = false
      await route.abort('failed')
      return
    }
    await retryReleased
    await route.continue()
  })
  await page.goto(`/nfl/compare?${WARNER_VS_MCNAIR_SEARCH}`)

  const alert = page.getByRole('dialog').getByRole('alert')
  await expect(alert).toBeVisible()
  await closeButton(page).click()

  await expect(page.getByRole('dialog')).toHaveCount(0)
  const playerA = page.getByLabel('Player A', { exact: true })
  const playerB = page.getByLabel('Player B', { exact: true })
  await expect(playerA).toHaveValue(`Player #${WARNER}`)
  await expect(playerB).toHaveValue(`Player #${MCNAIR}`)
  const compare = page.getByRole('button', { name: 'Compare', exact: true })
  await expect(compare).toBeEnabled()
  await expect(compare).toBeFocused()

  await compare.click()

  await expect(page).toHaveURL(
    new RegExp(`/nfl/compare\\?${WARNER_VS_MCNAIR_SEARCH}$`),
  )
  // The retry is still out: loading, not the first failure's line.
  const reopened = page.getByRole('dialog')
  await expect(reopened.getByRole('status')).toHaveText(
    'Loading the comparison\u2026',
  )
  await expect(reopened.getByRole('alert')).toHaveCount(0)
  releaseRetry()

  await expect(
    comparisonModal(page, 'Kurt Warner and Steve McNair').getByRole('table', {
      name: 'Kurt Warner and Steve McNair, regular season',
    }),
  ).toBeVisible()

  // The answer named both players, so the fields name them after a close.
  await closeButton(page).click()
  await expect(playerA).toHaveValue('Kurt Warner')
  await expect(playerB).toHaveValue('Steve McNair')
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

// Issue #367: a lone link's failed career lookup is about that pick alone.
// Once another player is picked, the narrator's line goes and the form reads
// like any other. Since #436 Player B waits on Player A's group, which the
// failed lookup never said, so the other player is a new Player A.
test("a lone link's career failure goes once another player is picked", async ({
  page,
}) => {
  await page.route(
    (url) => url.pathname === `/api/players/${WARNER}`,
    (route) => route.abort('failed'),
  )
  await page.goto(`/nfl/compare?a=${WARNER}`)

  const alert = page.getByRole('alert')
  await expect(alert).toContainText('Lost you there')
  const playerA = page.getByLabel('Player A', { exact: true })
  const playerB = page.getByLabel('Player B', { exact: true })
  await expect(playerA).toHaveValue(`Player #${WARNER}`)
  await expect(playerB).toBeDisabled()

  await playerA.fill('')
  await playerA.pressSequentially('McNair')
  await page.getByRole('option', { name: /Steve McNair/ }).click()

  await expect(playerA).toHaveValue('Steve McNair')
  await expect(playerB).toBeEnabled()
  await expect(page.getByRole('alert')).toHaveCount(0)
  await expect(page.getByText(PICK_TWO_COPY)).toHaveCount(0)
})
