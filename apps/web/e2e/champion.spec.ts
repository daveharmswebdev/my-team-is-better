import { test, expect } from '@playwright/test'
import { fillYear } from './fillYear.ts'

// Golden-path smoke spec (issue #39) for the "champion" question type,
// against year 2005 -- the fixture db's most complete golden-dataset year
// (Texas is the 2005 keener champion, per apps/api's own test suite).
test('submitting a champion question renders a verdict for the 2005 champion', async ({
  page,
}) => {
  await page.goto('/')

  await page
    .getByLabel('What do you want to know?')
    .selectOption({ label: 'Who was the best team in a year?' })
  await fillYear(page, '2005')
  // The best-team question has no "Your team" field (issue #198).
  await expect(page.getByLabel('Your team (optional)')).toHaveCount(0)
  await page.getByRole('button', { name: 'Get the verdict' }).click()

  // The verdict opens in the modal over the form (issue #198).
  const verdict = page
    .getByRole('dialog', { name: 'The verdict' })
    .getByRole('article')
  await expect(verdict).toBeVisible()
  await expect(verdict.getByText('Solid case, no notes.')).toBeVisible()
  // `TeamCaseReceipts` labels its evidence section `${team_name} evidence` --
  // an unambiguous, team-specific anchor (unlike a bare text search, which
  // would also match substrings like "Texas Tech"/"Texas A&M" in the
  // rendered schedule).
  await expect(
    verdict.getByRole('region', { name: 'Texas evidence' }),
  ).toBeVisible()
})
