import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import { METHODS } from './api/types'
import { RATING_DISPLAY_DATA } from './formatRating'

/**
 * Issue #165 (epic #147 / #113): persona grounding in apps/api accepts a
 * rating quoted the way the card prints it (Keener x1000 to 2 decimals), so
 * apps/web's display scale is no longer display-only. apps/api owns the one
 * definition and publishes it as `apps/api/rating-display.json`; its own
 * suite fails when that file is stale. This file checks `formatRating`'s
 * per-method `scale`/`decimals` against it, so changing either side alone
 * fails CI. It belongs to apps/api: read it, never edit it.
 *
 * (Resolved from Vitest's cwd -- `apps/web` -- exactly as
 * `api/vocabularies.test.ts` resolves its file, for the same reason.)
 */
const RATING_DISPLAY_PATH = resolve(process.cwd(), '../api/rating-display.json')

interface PublishedDisplay {
  scale: number
  decimals: number
}

function loadRatingDisplay(): Record<string, PublishedDisplay> {
  // Throws (failing every test below) if the file is missing, not JSON, or
  // not the expected shape -- a missing contract must never pass by comparing
  // nothing.
  const parsed: unknown = JSON.parse(readFileSync(RATING_DISPLAY_PATH, 'utf8'))
  if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
    throw new Error(`${RATING_DISPLAY_PATH} is not a JSON object`)
  }
  const published: Record<string, PublishedDisplay> = {}
  for (const [method, entry] of Object.entries(parsed)) {
    if (typeof entry !== 'object' || entry === null || Array.isArray(entry)) {
      throw new Error(`${RATING_DISPLAY_PATH}: "${method}" is not an object`)
    }
    const { scale, decimals } = entry as Record<string, unknown>
    if (
      typeof scale !== 'number' ||
      !Number.isFinite(scale) ||
      scale <= 0 ||
      typeof decimals !== 'number' ||
      !Number.isInteger(decimals) ||
      decimals < 0
    ) {
      throw new Error(
        `${RATING_DISPLAY_PATH}: "${method}" needs a positive finite scale and a non-negative integer decimals`,
      )
    }
    published[method] = { scale, decimals }
  }
  return published
}

describe('published rating display scale (issue #165)', () => {
  const published = loadRatingDisplay()

  it('parsed a real Keener scale (floor: never vacuous)', () => {
    expect(published['keener']?.scale).toBeGreaterThan(1)
  })

  it('publishes exactly the methods in METHODS, in both directions', () => {
    expect(Object.keys(published).sort()).toEqual([...METHODS].sort())
  })

  it("mirrors exactly METHODS in apps/web's display data", () => {
    expect(Object.keys(RATING_DISPLAY_DATA).sort()).toEqual([...METHODS].sort())
  })

  it.each(METHODS)(
    "%s: apps/web's scale and decimals equal the published ones",
    (method) => {
      const web = RATING_DISPLAY_DATA[method]
      expect({
        method,
        scale: web.scale,
        decimals: web.decimals,
      }).toEqual({ method, ...published[method] })
    },
  )
})
