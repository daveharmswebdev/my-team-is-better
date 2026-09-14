import { expect } from '@playwright/test'
import type { Page } from '@playwright/test'

/**
 * Types a season into `QuestionForm`'s Year field once the field has settled
 * (issue #197).
 *
 * The field starts empty and fills in the newest season (2019 in the fixture
 * db) when `/api/years` answers. `locator.fill()` selects all and then
 * inserts, so if that answer lands in between, both end up in the field:
 * "20192005". `parseYear` rejects that, "Get the verdict" stays disabled, and
 * a spec used to fail 30s later on the click rather than on the Year field.
 *
 * So this waits for the default to show up first, then checks the field holds
 * exactly what was typed, and fails on the Year field if it doesn't.
 *
 * The year list is keyed by league and engine, so switching either one empties
 * the default again until that list loads. Call this after any League or
 * Engine change: waiting before the switch would pass against the previous
 * engine's stale default.
 */
export async function fillYear(page: Page, year: string): Promise<void> {
  const field = page.getByLabel('Year')
  await expect(
    field,
    'Year never showed its default season: /api/years has not loaded',
  ).not.toHaveValue('')
  await field.fill(year)
  await expect(
    field,
    `Year should read exactly ${year} after typing it (a late default can leave "2019${year}")`,
  ).toHaveValue(year)
}
