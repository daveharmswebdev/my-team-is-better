import { describe, expect, it } from 'vitest'
import * as fixtures from './playerFixtures'

/**
 * Every `sack_yards_lost` anywhere inside a value, with the path that leads
 * to it, so a failure names the fixture that carries the wrong sign.
 */
function sackYardsLost(
  value: unknown,
  path: string,
): { path: string; value: unknown }[] {
  if (Array.isArray(value)) {
    return value.flatMap((item, index) =>
      sackYardsLost(item, `${path}[${index}]`),
    )
  }
  if (value !== null && typeof value === 'object') {
    return Object.entries(value as Record<string, unknown>).flatMap(
      ([key, child]) =>
        key === 'sack_yards_lost'
          ? [{ path: `${path}.${key}`, value: child }]
          : sackYardsLost(child, `${path}.${key}`),
    )
  }
  return []
}

describe('player fixtures (issue #298)', () => {
  const found = Object.entries(fixtures).flatMap(([name, value]) =>
    sackYardsLost(value, name),
  )

  it('walks fixtures that carry sack yards', () => {
    expect(found.length).toBeGreaterThan(19)
  })

  it('stores sack yards lost positive, the way the API publishes them', () => {
    const negative = found.filter(
      ({ value }) => typeof value === 'number' && value < 0,
    )
    expect(negative).toEqual([])
  })

  it("reads Kurt Warner's 1999 regular season as 26 sacks for 176 yards", () => {
    expect(fixtures.WARNER_1999_REGULAR.stats.sacks_suffered).toBe(26)
    expect(fixtures.WARNER_1999_REGULAR.stats.sack_yards_lost).toBe(176)
    expect(fixtures.KURT_WARNER_REGULAR.stats.sack_yards_lost).toBe(176)
  })
})
