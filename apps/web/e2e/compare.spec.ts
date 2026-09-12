import { test, expect } from '@playwright/test'
import { pickTeam } from './pickTeam.ts'

// Golden-path smoke spec (issue #39) for the "compare" question type,
// against year 2005, Texas vs USC -- the existing golden comparison used
// throughout apps/api's own test suite.
test('submitting a compare question renders a verdict comparing Texas and USC in 2005', async ({
  page,
}) => {
  await page.goto('/')

  await page
    .getByLabel('What do you want to know?')
    .selectOption({ label: 'Was one team better than another?' })
  await page.getByLabel('Year').fill('2005')
  await pickTeam(page, 'Team A', 'Texas')
  await pickTeam(page, 'Team B', 'USC')
  await page.getByRole('button', { name: 'Get the verdict' }).click()

  const verdict = page.getByRole('article')
  await expect(verdict).toBeVisible()
  await expect(verdict.getByText('Solid case, no notes.')).toBeVisible()
  // `ComparisonReceipts`' `TeamSummary` renders each team's exact name as its
  // own <h4> heading -- an unambiguous anchor (unlike a bare text search,
  // which would also match substrings like "Texas Tech"/"Texas A&M" in the
  // rendered common-opponents list).
  await expect(
    verdict.getByRole('heading', { name: 'Texas', exact: true }),
  ).toBeVisible()
  await expect(
    verdict.getByRole('heading', { name: 'USC', exact: true }),
  ).toBeVisible()
})
