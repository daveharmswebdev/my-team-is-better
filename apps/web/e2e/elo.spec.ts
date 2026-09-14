import { test, expect } from '@playwright/test'

// Issue #154 (epic #147): the Engine toggle end to end. The fixture db holds
// `elo` ratings rows for 2001/2005/2013 alongside Keener's, and Texas is the
// 2005 Elo #1 (1933.19...), so a champion question asked of Elo answers with
// Texas on Elo's whole-point scale -- with no Keener breakdown (issue #153).
test('asking Elo labels the card with the answering engine, prints Elo’s scale, and offers no Keener breakdown', async ({
  page,
}) => {
  await page.goto('/')

  await page
    .getByRole('group', { name: 'Engine' })
    .getByRole('radio', { name: 'Elo (second opinion)' })
    .check()
  await page
    .getByLabel('What do you want to know?')
    .selectOption({ label: 'Who was the best team in a year?' })
  await page.getByLabel('Year').fill('2005')
  await page.getByRole('button', { name: 'Get the verdict' }).click()

  const verdict = page.getByRole('article')
  await expect(verdict).toBeVisible()
  await expect(verdict.getByText('Engine: Elo (second opinion)')).toBeVisible()

  const receipts = verdict.getByRole('region', { name: 'Texas evidence' })
  await expect(receipts).toContainText('Rating 1,933')
  await expect(
    receipts.getByText(
      'Elo builds its rating game by game, in date order, with margin of victory counted — it has no per-opponent breakdown to show.',
    ),
  ).toBeVisible()
  await expect(verdict.locator('[aria-haspopup="dialog"]')).toHaveCount(0)
  await expect(verdict).not.toContainText('Keener')
})
