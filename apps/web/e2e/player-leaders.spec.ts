import { test, expect } from '@playwright/test'
import type { Locator, Page } from '@playwright/test'

// Issue #296: the NFL leaders and a player's career page, end to end against
// the real API on the committed fixture db (NFL 1999 + 2023 player stats).
// Every number here was measured on that fixture: 204 regular-season
// players, 30 postseason, Kurt Warner's 1999 with one Rams game the source
// has no stat lines for.

function leadersTable(page: Page, name: string): Locator {
  return page.getByRole('table', { name: `NFL career leaders: ${name}` })
}

/** The `index`th body row (0-based). */
function bodyRow(table: Locator, index: number): Locator {
  return table.locator('tbody tr').nth(index)
}

async function expectRow(
  table: Locator,
  index: number,
  rank: string,
  player: string,
) {
  const row = bodyRow(table, index)
  await expect(row.locator('td').first()).toHaveText(rank)
  await expect(row.getByRole('rowheader')).toHaveText(player)
}

test('the nav opens the leaders, with Tua Tagovailoa first on 4,624 passing yards', async ({
  page,
}) => {
  await page.goto('/')
  await page
    .getByRole('navigation', { name: 'Primary' })
    .getByRole('link', { name: 'NFL Leaders' })
    .click()

  await expect(page).toHaveURL(/\/nfl\/leaders$/)
  const table = leadersTable(page, 'regular season, by passing yards')
  await expectRow(table, 0, '1', 'Tua Tagovailoa')
  await expect(bodyRow(table, 0)).toContainText('4,624')
  await expect(
    table.getByRole('columnheader', { name: 'Passing yards' }),
  ).toHaveAttribute('aria-sort', 'descending')
  await expect(page.getByText('1–50 of 204')).toBeVisible()
})

test('sorting by passing TDs puts Kurt Warner first and ties Dak Prescott and Steve Beuerlein at 2', async ({
  page,
}) => {
  await page.goto('/nfl/leaders')
  await expect(
    leadersTable(page, 'regular season, by passing yards'),
  ).toBeVisible()

  await page.getByRole('button', { name: 'Passing TDs' }).click()

  const table = leadersTable(page, 'regular season, by passing TDs')
  await expectRow(table, 0, '1', 'Kurt Warner')
  await expectRow(table, 1, '2', 'Dak Prescott')
  await expectRow(table, 2, '2', 'Steve Beuerlein')
  await expectRow(table, 3, '4', 'Jordan Love')
  await expect(
    table.getByRole('columnheader', { name: 'Passing TDs' }),
  ).toHaveAttribute('aria-sort', 'descending')
  await expect(page).toHaveURL(/sort=passing_tds/)

  // Back restores the table before.
  await page.goBack()
  await expectRow(
    leadersTable(page, 'regular season, by passing yards'),
    0,
    '1',
    'Tua Tagovailoa',
  )
})

test('Playoffs by starter wins puts Patrick Mahomes first at 4-0, from the keyboard', async ({
  page,
}) => {
  await page.goto('/nfl/leaders')
  await expect(
    leadersTable(page, 'regular season, by passing yards'),
  ).toBeVisible()

  await page.getByRole('radio', { name: 'Regular season' }).focus()
  await page.keyboard.press('ArrowRight')
  await expect(page.getByRole('radio', { name: 'Playoffs' })).toBeChecked()
  await expect(leadersTable(page, 'playoffs, by passing yards')).toBeVisible()
  await page.getByRole('button', { name: 'Starter record' }).focus()
  await page.keyboard.press('Enter')

  const table = leadersTable(page, 'playoffs, by starter wins')
  await expectRow(table, 0, '1', 'Patrick Mahomes')
  await expect(bodyRow(table, 0)).toContainText('4-0')
  await expectRow(table, 1, '2', 'Kurt Warner')
  await expectRow(table, 2, '2', 'Steve McNair')
  await expect(page.getByText('1–30 of 30')).toBeVisible()
  await expect(page).toHaveURL(/season_type=postseason&sort=wins&offset=0/)
})

test('paging reaches rank 51, survives a reload, and Back returns to the first page', async ({
  page,
}) => {
  await page.goto('/nfl/leaders')
  await expect(page.getByText('1–50 of 204')).toBeVisible()

  await page.getByRole('button', { name: 'Next page' }).click()

  await expect(page.getByText('51–100 of 204')).toBeVisible()
  const table = leadersTable(page, 'regular season, by passing yards')
  await expectRow(table, 0, '51', 'Mac Jones')
  await expect(page).toHaveURL(/offset=50/)

  await page.reload()
  await expectRow(
    leadersTable(page, 'regular season, by passing yards'),
    0,
    '51',
    'Mac Jones',
  )

  await page.goBack()
  await expect(page.getByText('1–50 of 204')).toBeVisible()
  await expectRow(
    leadersTable(page, 'regular season, by passing yards'),
    0,
    '1',
    'Tua Tagovailoa',
  )
})

test("Kurt Warner's name opens his career: 1999 St. Louis Rams, 4,044 yards, and the one-game disclosure", async ({
  page,
}) => {
  await page.goto('/nfl/leaders?season_type=regular&sort=passing_tds&offset=0')

  await page.getByRole('link', { name: 'Kurt Warner' }).click()

  await expect(page).toHaveURL(/\/nfl\/players\/2044124519$/)
  await expect(
    page.getByRole('heading', { level: 1, name: 'Kurt Warner' }),
  ).toBeVisible()
  const regular = page.getByRole('table', {
    name: 'Kurt Warner, regular season',
  })
  const line = regular.locator('tbody tr').first()
  await expect(line.getByRole('rowheader')).toHaveText('1999')
  await expect(line).toContainText('St. Louis Rams')
  await expect(line).toContainText('4,044')
  await expect(line).toContainText(
    'Totals undercount 1 game: the source has no stat lines for it.',
  )
  await expect(
    regular.getByRole('rowheader', { name: 'Career, 1 season' }),
  ).toBeVisible()

  const playoffs = page.getByRole('table', { name: 'Kurt Warner, playoffs' })
  await expect(playoffs.locator('tbody tr').first()).toContainText('1,063')
  await expect(playoffs).not.toContainText('undercount')
  await expect(page.getByText(/undercount/)).toHaveCount(1)
  for (const header of await page.getByRole('columnheader').allTextContents()) {
    expect(header).not.toMatch(/sack/i)
  }

  // Back lands on the same sorted table.
  await page.goBack()
  await expectRow(
    leadersTable(page, 'regular season, by passing TDs'),
    0,
    '1',
    'Kurt Warner',
  )
})

test('an unknown player gets the narrator, not a status code', async ({
  page,
}) => {
  await page.goto('/nfl/players/1')

  const alert = page.getByRole('alert')
  await expect(alert).toContainText('Never heard of him, pal.')
  await expect(alert).not.toContainText('404')
  await alert.getByRole('link', { name: /leaders board/ }).click()
  await expect(page).toHaveURL(/\/nfl\/leaders$/)
})

test('the nflfastR credit is linked on both player pages and on the About page', async ({
  page,
}) => {
  const credit = (scope: Page | Locator) =>
    scope.getByRole('link', {
      name: 'nflverse player stats (nflfastR, by Sebastian Carl and Ben Baldwin)',
    })

  await page.goto('/nfl/leaders')
  await expect(credit(page)).toBeVisible()
  await expect(credit(page)).toHaveAttribute(
    'href',
    'https://github.com/nflverse/nflfastR',
  )

  await page.goto('/nfl/players/2044124519')
  await expect(credit(page)).toBeVisible()

  await page.goto('/about')
  const paragraph = page.locator('p').filter({ has: credit(page) })
  await expect(paragraph).toContainText(
    'The NFL player stats on the leaders and player pages come from',
  )
  await expect(paragraph).not.toContainText('Every game result')
})
