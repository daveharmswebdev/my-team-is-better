import { describe, expect, it } from 'vitest'
import { formatRating } from './formatRating'

describe('formatRating', () => {
  it('scales a typical positive eigenvector-scale rating by 1000 and formats to 2 decimals', () => {
    expect(formatRating(0.00877)).toBe('8.77')
  })

  it('scales a negative rating diff by 1000 and formats to 2 decimals', () => {
    expect(formatRating(-0.00275)).toBe('-2.75')
  })

  it('formats zero as 0.00', () => {
    expect(formatRating(0)).toBe('0.00')
  })

  it('rounds to 2 decimal places', () => {
    expect(formatRating(0.0060216)).toBe('6.02')
  })
})
