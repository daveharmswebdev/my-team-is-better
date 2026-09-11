import { test, expect } from '@playwright/test'

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
  await page.getByLabel('Year').fill('2005')
  await page.getByRole('button', { name: 'Get the verdict' }).click()

  const verdict = page.getByRole('article')
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
