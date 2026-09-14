import { test, expect } from '@playwright/test'
import { fillYear } from './fillYear.ts'
import { pickTeam } from './pickTeam.ts'

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
  await fillYear(page, '2005')
  // `pickTeam` matches the label exactly -- a substring match would also hit
  // the "Your team (optional)" field, which team_case shows (champion alone
  // doesn't, since issue #198).
  await pickTeam(page, 'Team', 'USC')
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
