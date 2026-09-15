import { describe, expect, it } from 'vitest'
import { methodologyId } from './methodologyId'

/**
 * The two names the live `/api/credits` sends (measured in
 * `packages/cfb-engine/src/cfb_strength/evidence/credits.py`). These ids are
 * link targets -- `EloLedgerDisclosure` points at `/about#elo` -- so a change
 * here is a change to a URL.
 */
describe('methodologyId', () => {
  it('slugs "Elo" to "elo"', () => {
    expect(methodologyId('Elo')).toBe('elo')
  })

  it('slugs "Keener\'s method" to "keeners-method"', () => {
    expect(methodologyId("Keener's method")).toBe('keeners-method')
  })

  it('collapses runs of punctuation and whitespace and trims the ends', () => {
    expect(methodologyId('  Colley -- Matrix  (v2)! ')).toBe('colley-matrix-v2')
  })
})
