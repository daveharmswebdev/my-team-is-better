import { test, expect } from '@playwright/test'

// Golden-path smoke spec (issue #39) for the "team_case" question type,
// against year 2005 / USC -- part of the existing Texas/USC golden
// comparison used throughout apps/api's own test suite.
test('submitting a team-case question renders a verdict for USC in 2005', async ({
  page,
}) => {
  await page.goto('/')

  await page
    .getByLabel('What do you want to know?')
    .selectOption({ label: 'How good was a team in a year?' })
  await page.getByLabel('Year').fill('2005')
  // `exact: true` -- a substring match would also hit the always-present
  // "Your team (optional)" field's label.
  await page.getByLabel('Team', { exact: true }).fill('USC')
  await page.getByRole('button', { name: 'Get the verdict' }).click()

  const verdict = page.getByRole('article')
  await expect(verdict).toBeVisible()
  await expect(verdict.getByText('Solid case, no notes.')).toBeVisible()
  // `TeamCaseReceipts` labels its evidence section `${team_name} evidence` --
  // an unambiguous, team-specific anchor for "USC" appearing in the render.
  await expect(
    verdict.getByRole('region', { name: 'USC evidence' }),
  ).toBeVisible()
})
