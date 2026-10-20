import { test, expect } from '@playwright/test'

// Issue #268: one uncaught page error must not blank the whole app. This
// reproduces the #227 failure for real: AboutPage's hash-scroll effect calls
// `scrollIntoView` once the credits load, so making that throw is an effect
// error in a production build. The shell's route-level boundary must show the
// narrator's fallback, keep the nav, and clear when the visitor moves on.

test('a page that throws in an effect shows the fallback, keeps the nav, and recovers on navigation', async ({
  page,
}) => {
  await page.addInitScript(() => {
    Element.prototype.scrollIntoView = function scrollIntoView() {
      throw new Error('e2e: forced scrollIntoView failure (issue #268)')
    }
  })

  await page.goto('/about#methods')

  const alert = page.getByRole('alert')
  await expect(alert).toContainText("That's on us, not you.")
  await expect(alert).not.toContainText('forced scrollIntoView')
  const nav = page.getByRole('navigation', { name: 'Primary' })
  await expect(nav).toBeVisible()

  await nav.getByRole('link', { name: 'NFL Leaders' }).click()

  await expect(page).toHaveURL(/\/nfl\/leaders$/)
  await expect(
    page.getByRole('table', {
      name: 'NFL career leaders: regular season, by passing yards',
    }),
  ).toBeVisible()
  await expect(page.getByRole('alert')).toHaveCount(0)
})
