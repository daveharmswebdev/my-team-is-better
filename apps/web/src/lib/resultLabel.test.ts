import { describe, expect, it } from 'vitest'
import { resultLabel } from './resultLabel'

describe('resultLabel', () => {
  it('spells out each single-game result as a word', () => {
    expect(resultLabel('W')).toBe('Win')
    expect(resultLabel('L')).toBe('Loss')
    expect(resultLabel('T')).toBe('Tie')
  })
})
