import { describe, expect, it } from 'vitest'
import { METHODS } from './api/types'
import { displayRatingPair, formatRating } from './formatRating'

describe('displayRatingPair', () => {
  it('Elo: a leader beside a raw sub-point diff gets the diff of the printed numbers', () => {
    // 1531.5 prints 1,532 and 1531.4 prints 1,531: 1532 - 1531 = 1, A leads.
    expect(displayRatingPair(1531.5, 1531.4, 'elo')).toEqual({
      a: '1,532',
      b: '1,531',
      diff: '1',
      leader: 'a',
    })
  })

  it('Elo: two ratings that print identically are the same, with a zero diff, despite a raw diff near 1', () => {
    // 1531.49 prints 1,531 and 1530.5 prints 1,531 (Math.round takes .5 up).
    expect(displayRatingPair(1531.49, 1530.5, 'elo_career')).toEqual({
      a: '1,531',
      b: '1,531',
      diff: '0',
      leader: null,
    })
  })

  it('Keener: two ratings that print identically are the same, and the diff never prints a signed zero', () => {
    // Both print 3.50; the raw diff (-0.0000098 -> "-0.01") is not used.
    expect(displayRatingPair(0.0034951, 0.0035049, 'keener')).toEqual({
      a: '3.50',
      b: '3.50',
      diff: '0.00',
      leader: null,
    })
  })

  it('Keener: a one-hundredth display gap prints exactly 0.01, free of float noise', () => {
    // 3.50 - 3.49 in floating point is 0.010000000000000231.
    expect(displayRatingPair(0.0035, 0.00349, 'keener')).toEqual({
      a: '3.50',
      b: '3.49',
      diff: '0.01',
      leader: 'a',
    })
  })

  it('Keener: names team_b the leader with a negative diff', () => {
    expect(displayRatingPair(0.00602, 0.00877, 'keener')).toEqual({
      a: '6.02',
      b: '8.77',
      diff: '-2.75',
      leader: 'b',
    })
  })

  it('Elo: rounds negative halves with one rule for both sides', () => {
    // Math.round(-12.5) is -12 and Math.round(-13.5) is -13: diff 1.
    expect(displayRatingPair(-12.5, -13.5, 'elo')).toEqual({
      a: '-12',
      b: '-13',
      diff: '1',
      leader: 'a',
    })
  })

  it.each(METHODS)(
    '%s: prints each side exactly as formatRating does',
    (method) => {
      // 0.003505 sits on a binary half-boundary for Keener's toFixed.
      for (const [x, y] of [
        [0.003505, 0.003495],
        [1531.5, 1530.5],
        [0.0060216, 0.00877],
      ] as const) {
        const pair = displayRatingPair(x, y, method)
        expect([pair.a, pair.b]).toEqual([
          formatRating(x, method),
          formatRating(y, method),
        ])
      }
    },
  )
})

describe('formatRating', () => {
  describe('keener', () => {
    it('scales a typical positive eigenvector-scale rating by 1000 and formats to 2 decimals', () => {
      expect(formatRating(0.00877, 'keener')).toBe('8.77')
    })

    it('scales a negative rating diff by 1000 and formats to 2 decimals', () => {
      expect(formatRating(-0.00275, 'keener')).toBe('-2.75')
    })

    it('formats zero as 0.00', () => {
      expect(formatRating(0, 'keener')).toBe('0.00')
    })

    it('rounds to 2 decimal places', () => {
      expect(formatRating(0.0060216, 'keener')).toBe('6.02')
    })

    it('never renders "-0.00" for a diff that rounds to zero', () => {
      // A near-tie comparison (#149's Keener pairs) shows this diff right
      // beside "rate the same at display precision" -- a signed zero there
      // would contradict it.
      expect(formatRating(-0.0000003, 'keener')).toBe('0.00')
    })
  })

  describe.each(['elo', 'elo_career'] as const)('%s', (method) => {
    it('rounds to an integer with an en-US thousands separator', () => {
      expect(formatRating(1684.4, method)).toBe('1,684')
    })

    it('rounds a half up', () => {
      expect(formatRating(1499.5, method)).toBe('1,500')
    })

    it('formats a negative rating diff as a negative integer', () => {
      expect(formatRating(-12.3, method)).toBe('-12')
    })

    it('never renders "-0" for a small negative diff', () => {
      expect(formatRating(-0.4, method)).toBe('0')
    })

    it('formats zero as 0', () => {
      expect(formatRating(0, method)).toBe('0')
    })

    it('never applies the Keener x1000 scale', () => {
      expect(formatRating(1684.4, method)).not.toBe('1684400.00')
    })
  })

  it('has a display rule for every method in METHODS', () => {
    expect(METHODS.length).toBeGreaterThan(0)
    for (const method of METHODS) {
      expect({ method, formatted: formatRating(0.5, method) }).toEqual({
        method,
        formatted: expect.stringMatching(/\S/),
      })
    }
  })
})
