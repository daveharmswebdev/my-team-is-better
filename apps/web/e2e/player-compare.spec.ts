import { test, expect } from '@playwright/test'
import type { Locator } from '@playwright/test'

// Issue #301: the NFL player comparison, end to end against the real API on
// the committed fixture db (NFL 1999 + 2023). Every number here was measured
// on that fixture: Kurt Warner's 4,044 regular-season yards to Steve McNair's
// 2,179, McNair's 4 playoff games to Warner's 3, and their two games as
// opposing starters, 1999 week 8 (Titans 24, Rams 21) and week 21 (Rams 23,
// Titans 16).

const WARNER = '2044124519'
const MCNAIR = '2385180619'

/** A totals row's two value cells, player A's first. */
function valueCells(table: Locator, label: string): Locator {
  return table
    .locator('tbody tr')
    .filter({
      has: table.page().getByRole('rowheader', { name: label, exact: true }),
    })
    .getByRole('cell')
}

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

  await playerB.pressSequentially('McNair')
  await page.getByRole('option', { name: /Steve McNair/ }).click()

  await expect(page).toHaveURL(
    new RegExp(`/nfl/compare\\?a=${WARNER}&b=${MCNAIR}$`),
  )
  await expect(playerB).toHaveValue('Steve McNair')

  const regular = page.getByRole('table', {
    name: 'Kurt Warner and Steve McNair, regular season',
  })
  const yards = valueCells(regular, 'Passing yards')
  await expect(yards.nth(0)).toContainText('4,044')
  await expect(yards.nth(0)).toContainText('(larger number)')
  await expect(yards.nth(1)).toHaveText('2,179')

  const playoffs = page.getByRole('table', {
    name: 'Kurt Warner and Steve McNair, playoffs',
  })
  const games = valueCells(playoffs, 'Games')
  await expect(games.nth(0)).toHaveText('3')
  await expect(games.nth(1)).toContainText('(larger number)')

  const headToHead = page.getByRole('region', { name: 'Head to head' })
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

  // A reload keeps both players.
  await page.reload()
  await expect(playerA).toHaveValue('Kurt Warner')
  await expect(playerB).toHaveValue('Steve McNair')
  await expect(valueCells(regular, 'Passing yards').nth(0)).toContainText(
    '4,044',
  )

  // Back returns to Warner alone.
  await page.goBack()
  await expect(page).toHaveURL(new RegExp(`/nfl/compare\\?a=${WARNER}$`))
  await expect(playerA).toHaveValue('Kurt Warner')
  await expect(playerB).toHaveValue('')
  await expect(regular).toHaveCount(0)
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
})

test('an unknown player gets the narrator, not a status code', async ({
  page,
}) => {
  await page.goto(`/nfl/compare?a=${WARNER}&b=1`)

  const alert = page.getByRole('alert')
  await expect(alert).toContainText('Never heard of him, pal.')
  await expect(alert).not.toContainText('404')
  await expect(
    alert.getByRole('link', { name: /leaders board/ }),
  ).toHaveAttribute('href', '/nfl/leaders')
})
