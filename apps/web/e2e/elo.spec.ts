import { test, expect } from '@playwright/test'
import type { Locator, Page } from '@playwright/test'
import {
  roundsToPrintedShift,
  withinATenthOfPrintedShift,
} from './eloWorkedStep.ts'
import { pickTeam } from './pickTeam.ts'

// Issues #154 and #183 (epic #147): the Engine toggle end to end, against the
// real API and the committed fixture db. The fixture holds `elo` ratings and
// ledgers for 2005 (k 40, 100 points of home field), and Texas is the 2005 Elo
// #1 (1933.19...) with 13 games. An Elo rating shows the engine's game-by-game
// work, replacing #153's "no per-opponent breakdown" explainer.

/** #153's retired explainer, which #183 replaced with the ledger itself. */
const RETIRED_EXPLAINER =
  'Elo builds its rating game by game, in date order, with margin of victory counted — it has no per-opponent breakdown to show.'

/** Both 2005 ledgers in the fixture have 13 games. */
const GAMES_2005 = 13

async function chooseElo(page: Page) {
  await page.goto('/')
  await page
    .getByRole('group', { name: 'Engine' })
    .getByRole('radio', { name: 'Elo (second opinion)' })
    .check()
}

/** Hovers a rating trigger and returns the ledger dialog named for `teamName`. */
async function openLedger(
  page: Page,
  trigger: Locator,
  teamName: string,
): Promise<Locator> {
  await trigger.hover()
  const dialog = page.getByRole('dialog', {
    name: `${teamName} Elo rating, game by game`,
  })
  await expect(dialog).toBeVisible()
  await expect(page.getByRole('dialog')).toHaveCount(1)
  return dialog
}

function gamesInOrder(dialog: Locator): Locator {
  return dialog
    .getByRole('list', { name: 'Games, in order' })
    .getByRole('listitem')
}

/** Every game's printed worked step, in order. */
async function workedSteps(dialog: Locator): Promise<string[]> {
  return gamesInOrder(dialog).getByText(' = gap ').allTextContents()
}

test('asking Elo for the 2005 champion shows Texas’s Elo rating game by game, with work a calculator can check', async ({
  page,
}) => {
  await chooseElo(page)
  await page
    .getByLabel('What do you want to know?')
    .selectOption({ label: 'Who was the best team in a year?' })
  await page.getByLabel('Year').fill('2005')
  await page.getByRole('button', { name: 'Get the verdict' }).click()

  const verdict = page.getByRole('article')
  await expect(verdict).toBeVisible()
  await expect(verdict.getByText('Engine: Elo (second opinion)')).toBeVisible()

  const receipts = verdict.getByRole('region', { name: 'Texas evidence' })
  const trigger = receipts.getByRole('button', { name: '1,933', exact: true })
  await expect(trigger).toHaveText('1,933')
  await expect(trigger).toHaveAttribute('aria-haspopup', 'dialog')
  await expect(verdict.getByText(RETIRED_EXPLAINER)).toHaveCount(0)
  await expect(verdict).not.toContainText('no per-opponent breakdown')

  const dialog = await openLedger(page, trigger, 'Texas')

  // The rule, with the fixture's constants: k 40, 100 points of home field.
  await expect(
    dialog.getByText(
      'Gap = team rating − opponent rating, ± 100 for home field (0 at a neutral site)',
      { exact: true },
    ),
  ).toBeVisible()
  await expect(
    dialog.getByText(
      'Rating change = 40 × multiplier × (result − win expectancy), where result is 1 for a win, ½ for a tie, 0 for a loss',
      { exact: true },
    ),
  ).toBeVisible()

  await expect(gamesInOrder(dialog)).toHaveCount(GAMES_2005)
  await expect(
    dialog.getByText('The card rounds this to 1,933.', { exact: true }),
  ).toBeVisible()

  // A fan with a calculator: every row's printed operands multiply out to
  // its printed change, rounded to the tenth.
  const steps = await workedSteps(dialog)
  expect(steps).toHaveLength(GAMES_2005)
  expect(steps.filter((work) => !roundsToPrintedShift(work))).toEqual([])

  await expect(verdict).not.toContainText('Keener')
})

test('an Elo comparison of Texas and USC in 2005 shows each team’s own ledger, every row within a tenth', async ({
  page,
}) => {
  await chooseElo(page)
  await page
    .getByLabel('What do you want to know?')
    .selectOption({ label: 'Was one team better than another?' })
  await page.getByLabel('Year').fill('2005')
  await pickTeam(page, 'Team A', 'Texas')
  await pickTeam(page, 'Team B', 'USC')
  await page.getByRole('button', { name: 'Get the verdict' }).click()

  const verdict = page.getByRole('article')
  await expect(verdict).toBeVisible()
  await expect(verdict.getByText('Engine: Elo (second opinion)')).toBeVisible()

  // Team A's summary renders before team B's.
  const triggers = verdict.locator('[aria-haspopup="dialog"]')
  await expect(triggers).toHaveCount(2)

  for (const [index, teamName] of [
    [0, 'Texas'],
    [1, 'USC'],
  ] as const) {
    const dialog = await openLedger(page, triggers.nth(index), teamName)
    await expect(gamesInOrder(dialog)).toHaveCount(GAMES_2005)

    const steps = await workedSteps(dialog)
    expect(steps).toHaveLength(GAMES_2005)
    expect(steps.filter((work) => !withinATenthOfPrintedShift(work))).toEqual(
      [],
    )

    // Pointer away, so this popover can't cover the next team's trigger.
    await page.mouse.move(0, 0)
    await expect(page.getByRole('dialog')).toHaveCount(0)
  }
})
