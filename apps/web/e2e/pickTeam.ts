import { expect } from '@playwright/test'
import type { Page } from '@playwright/test'

/**
 * Fills one of `QuestionForm`'s team fields by driving the real typeahead
 * (issue #80): type, wait for the suggestion, click it.
 *
 * Three things make this more than `locator.fill()`.
 *
 * 1. The fields are `TeamCombobox`es now, so picking a suggestion is the
 *    interaction actually worth smoke-testing -- and it submits the
 *    canonical team name rather than whatever was typed.
 * 2. `/api/teams` is year-scoped and its refetch is debounced, so right
 *    after a `Year` change the field is still the degraded plain input for
 *    the previous (or empty) catalog. Waiting for `role="combobox"` makes
 *    that transition deterministic instead of a race against the debounce.
 * 3. The label lookup is `exact` on purpose: an open listbox carries
 *    `aria-label="Team A suggestions"`, which a substring `getByLabel('Team
 *    A')` would also match -- a strict-mode violation that only appears
 *    once the suggestions are showing.
 */
export async function pickTeam(
  page: Page,
  label: string,
  team: string,
): Promise<void> {
  const field = page.getByLabel(label, { exact: true })
  await expect(field).toHaveAttribute('role', 'combobox')
  await field.fill(team)
  await page.getByRole('option', { name: team, exact: true }).click()
  await expect(field).toHaveValue(team)
}
