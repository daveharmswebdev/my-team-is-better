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

// Issue #312: the rushing board. Measured on the same fixture db: 653
// regular-season qualifiers (every player with a carry, quarterbacks
// included), Edgerrin James first on 1,553 yards and 369 carries, and a real
// tie at rank 3 by rushing touchdowns between two quarterbacks.

test('choosing Rushing ranks Edgerrin James first on 1,553 yards, with its own columns', async ({
  page,
}) => {
  await page.goto('/nfl/leaders')
  await expect(
    leadersTable(page, 'regular season, by passing yards'),
  ).toBeVisible()

  await page.getByLabel('Stat category').selectOption('rushing')

  const table = leadersTable(page, 'regular season, by rushing yards')
  await expectRow(table, 0, '1', 'Edgerrin James')
  await expect(bodyRow(table, 0)).toContainText('1,553')
  await expect(bodyRow(table, 0)).toContainText('369')
  await expect(
    table.getByRole('columnheader', { name: 'Rushing yards' }),
  ).toHaveAttribute('aria-sort', 'descending')
  await expect(
    table.getByRole('columnheader', { name: 'Passing yards' }),
  ).toHaveCount(0)
  await expect(
    table.getByRole('columnheader', { name: 'Starter record' }),
  ).toHaveCount(0)
  await expect(page.getByText('1–50 of 653')).toBeVisible()
  await expect(page).toHaveURL(/category=rushing/)
})

test('Rushing TDs puts Raheem Mostert first and ties two quarterbacks at 3, and a reload shows the same board', async ({
  page,
}) => {
  await page.goto('/nfl/leaders?category=rushing')
  await expect(
    leadersTable(page, 'regular season, by rushing yards'),
  ).toBeVisible()

  await page.getByRole('button', { name: 'Rushing TDs' }).click()

  const table = leadersTable(page, 'regular season, by rushing TDs')
  await expectRow(table, 0, '1', 'Raheem Mostert')
  await expectRow(table, 1, '2', 'Stephen Davis')
  await expectRow(table, 2, '3', 'Jalen Hurts')
  await expectRow(table, 3, '3', 'Josh Allen')
  await expect(bodyRow(table, 2)).toContainText('QB')
  await expect(bodyRow(table, 3)).toContainText('QB')
  await expect(
    table.getByRole('columnheader', { name: 'Rushing TDs' }),
  ).toHaveAttribute('aria-sort', 'descending')
  await expect(page).toHaveURL(
    /category=rushing&season_type=regular&sort=rushing_tds&offset=0/,
  )

  await page.reload()
  const reloaded = leadersTable(page, 'regular season, by rushing TDs')
  await expectRow(reloaded, 0, '1', 'Raheem Mostert')
  await expectRow(reloaded, 3, '3', 'Josh Allen')
  await expect(
    reloaded.getByRole('columnheader', { name: 'Rushing TDs' }),
  ).toHaveAttribute('aria-sort', 'descending')
  await expect(page.getByLabel('Stat category')).toHaveValue('rushing')
})

test('Back from the rushing board returns to the passing one', async ({
  page,
}) => {
  await page.goto('/nfl/leaders')
  await expect(
    leadersTable(page, 'regular season, by passing yards'),
  ).toBeVisible()

  await page.getByLabel('Stat category').selectOption('rushing')
  await expect(
    leadersTable(page, 'regular season, by rushing yards'),
  ).toBeVisible()

  await page.goBack()

  await expectRow(
    leadersTable(page, 'regular season, by passing yards'),
    0,
    '1',
    'Tua Tagovailoa',
  )
  await expect(page.getByLabel('Stat category')).toHaveValue('passing')
})

// Issue #314: the receiving board. Measured on the same fixture db: 926
// regular-season qualifiers (every player with a target or a reception,
// whatever his position), Tyreek Hill first on 1,799 yards, 119 catches and
// 13 TDs, and a three-way tie at rank 1 by receiving TDs (Cris Carter, Mike
// Evans and Hill, 13 each), CeeDee Lamb next at rank 4.

test('choosing Receiving ranks Tyreek Hill first on 1,799 yards, with its own columns', async ({
  page,
}) => {
  await page.goto('/nfl/leaders')
  await expect(
    leadersTable(page, 'regular season, by passing yards'),
  ).toBeVisible()

  await page.getByLabel('Stat category').selectOption('Receiving')

  const table = leadersTable(page, 'regular season, by receiving yards')
  await expectRow(table, 0, '1', 'Tyreek Hill')
  await expect(bodyRow(table, 0)).toContainText('WR')
  await expect(bodyRow(table, 0)).toContainText('1,799')
  await expect(bodyRow(table, 0)).toContainText('119')
  await expect(bodyRow(table, 0)).toContainText('13')
  await expect(table.locator('thead th')).toHaveText([
    'Rank',
    'Player',
    'Position',
    'Seasons',
    'Games',
    'Receptions',
    'Receiving yards',
    'Receiving TDs',
  ])
  await expect(
    table.getByRole('columnheader', { name: 'Receiving yards' }),
  ).toHaveAttribute('aria-sort', 'descending')
  for (const gone of [
    'Passing yards',
    'Rushing yards',
    'Carries',
    'Starter record',
  ]) {
    await expect(table.getByRole('columnheader', { name: gone })).toHaveCount(0)
  }
  await expect(page.getByText('1–50 of 926')).toBeVisible()
  await expect(page).toHaveURL(
    /category=receiving&season_type=regular&sort=receiving_yards&offset=0/,
  )
})

test('Receiving TDs shows the three-way tie at rank 1, and a reload shows the same board', async ({
  page,
}) => {
  await page.goto('/nfl/leaders?category=receiving')
  await expect(
    leadersTable(page, 'regular season, by receiving yards'),
  ).toBeVisible()

  await page.getByRole('button', { name: 'Receiving TDs' }).click()

  const table = leadersTable(page, 'regular season, by receiving TDs')
  await expectRow(table, 0, '1', 'Cris Carter')
  await expectRow(table, 1, '1', 'Mike Evans')
  await expectRow(table, 2, '1', 'Tyreek Hill')
  await expectRow(table, 3, '4', 'CeeDee Lamb')
  await expect(
    table.getByRole('columnheader', { name: 'Receiving TDs' }),
  ).toHaveAttribute('aria-sort', 'descending')
  await expect(
    table.getByRole('columnheader', { name: 'Receiving yards' }),
  ).toHaveAttribute('aria-sort', 'none')
  await expect(page).toHaveURL(
    /category=receiving&season_type=regular&sort=receiving_tds&offset=0/,
  )

  await page.reload()
  const reloaded = leadersTable(page, 'regular season, by receiving TDs')
  await expectRow(reloaded, 0, '1', 'Cris Carter')
  await expectRow(reloaded, 2, '1', 'Tyreek Hill')
  await expect(
    reloaded.getByRole('columnheader', { name: 'Receiving TDs' }),
  ).toHaveAttribute('aria-sort', 'descending')
  await expect(page.getByLabel('Stat category')).toHaveValue('receiving')
})

/** The cell of `row` under the column whose header reads `name`. */
async function cellUnder(
  table: Locator,
  row: Locator,
  name: string,
): Promise<Locator> {
  const headers = await table.locator('thead th').allTextContents()
  const index = headers.indexOf(name)
  expect(index, `no column named ${name}`).toBeGreaterThanOrEqual(0)
  return row.locator('th, td').nth(index)
}

// Issue #315: kicking and punting. FG% and 50+ are not in the API's payload:
// the board derives them from the counts it was sent, and these numbers are
// the fixture's (Aubrey 2023: 36 of 38, 9 from 50-59 and 1 from 60+).
test('choosing Kicking ranks Olindo Mare first on 39 field goals, with its own columns and derived FG% and 50+', async ({
  page,
}) => {
  await page.goto('/nfl/leaders')
  await expect(
    leadersTable(page, 'regular season, by passing yards'),
  ).toBeVisible()

  await page.getByLabel('Stat category').selectOption('Kicking')

  const table = leadersTable(page, 'regular season, by field goals made')
  await expectRow(table, 0, '1', 'Olindo Mare')
  await expect(table.locator('thead th')).toHaveText([
    'Rank',
    'Player',
    'Position',
    'Seasons',
    'Games',
    'FG made',
    'FG att',
    'FG%',
    '50+',
    'Long',
    'XP made',
  ])
  const mare = bodyRow(table, 0)
  await expect(await cellUnder(table, mare, 'FG made')).toHaveText('39')
  await expect(await cellUnder(table, mare, 'FG att')).toHaveText('46')
  await expect(await cellUnder(table, mare, 'Long')).toHaveText('54')
  await expect(await cellUnder(table, mare, '50+')).toHaveText('3')
  await expect(await cellUnder(table, mare, 'XP made')).toHaveText('27')

  await expectRow(table, 1, '2', 'Brandon Aubrey')
  const aubrey = bodyRow(table, 1)
  await expect(await cellUnder(table, aubrey, 'FG%')).toHaveText('94.7%')
  await expect(await cellUnder(table, aubrey, 'Long')).toHaveText('60')
  await expect(await cellUnder(table, aubrey, '50+')).toHaveText('10')

  await expect(
    table.getByRole('columnheader', { name: 'FG made' }),
  ).toHaveAttribute('aria-sort', 'descending')
  await expect(
    table.getByRole('columnheader', { name: 'Starter record' }),
  ).toHaveCount(0)
  await expect(page.getByText('1–50 of 81')).toBeVisible()
  await expect(page).toHaveURL(
    /category=kicking&season_type=regular&sort=fg_made&offset=0/,
  )
})

test('choosing Punting ranks Thomas Morstead first on 4,831 yards', async ({
  page,
}) => {
  await page.goto('/nfl/leaders')
  await expect(
    leadersTable(page, 'regular season, by passing yards'),
  ).toBeVisible()

  await page.getByLabel('Stat category').selectOption('Punting')

  const table = leadersTable(page, 'regular season, by punting yards')
  await expectRow(table, 0, '1', 'Thomas Morstead')
  await expectRow(table, 1, '2', 'Chris Gardocki')
  await expect(table.locator('thead th')).toHaveText([
    'Rank',
    'Player',
    'Position',
    'Seasons',
    'Games',
    'Punts',
    'Yards',
    'Net yards',
    'Inside 20',
  ])
  const morstead = bodyRow(table, 0)
  await expect(await cellUnder(table, morstead, 'Yards')).toHaveText('4,831')
  await expect(await cellUnder(table, morstead, 'Punts')).toHaveText('99')
  await expect(page.getByText('1–50 of 83')).toBeVisible()
})

test('sorting Kicking by FG% says no kicker has reached 100 attempts, and offers the default sort back', async ({
  page,
}) => {
  await page.goto('/nfl/leaders?category=kicking')
  await expect(
    leadersTable(page, 'regular season, by field goals made'),
  ).toBeVisible()

  await page.getByRole('button', { name: 'FG%' }).click()

  await expect(page).toHaveURL(
    /category=kicking&season_type=regular&sort=fg_pct&offset=0/,
  )
  await expect(
    page.getByText(
      'No kicker has reached 100 career field-goal attempts in the regular season, so nobody qualifies for the field-goal percentage board.',
    ),
  ).toBeVisible()
  await expect(
    page.getByText('No NFL player stats are loaded yet.'),
  ).toHaveCount(0)
  await expect(
    page.getByText(/ranks only kickers with at least 100 career field-goal/),
  ).toBeVisible()

  await page.getByRole('button', { name: 'Rank by field goals made' }).click()
  await expectRow(
    leadersTable(page, 'regular season, by field goals made'),
    0,
    '1',
    'Olindo Mare',
  )
})

test('a kicking deep link shows the same board after a reload, a never-made Long a dash named none', async ({
  page,
}) => {
  await page.goto(
    '/nfl/leaders?category=kicking&season_type=regular&sort=fg_made&offset=50',
  )

  const check = async () => {
    const table = leadersTable(page, 'regular season, by field goals made')
    await expect(page.getByLabel('Stat category')).toHaveValue('kicking')
    await expect(
      table.getByRole('columnheader', { name: 'FG made' }),
    ).toHaveAttribute('aria-sort', 'descending')
    await expect(page.getByText('51–81 of 81')).toBeVisible()
    const wright = table.locator('tbody tr').filter({
      has: page.getByRole('rowheader', { name: 'Matthew Wright' }),
    })
    await expect(wright.locator('td').first()).toHaveText('79')
    const long = await cellUnder(table, wright, 'Long')
    await expect(long).toHaveAccessibleName('none')
    await expect(long).not.toContainText('0')
    await expect(await cellUnder(table, wright, 'FG%')).toHaveText('0.0%')
  }

  await check()
  await page.reload()
  await check()
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
