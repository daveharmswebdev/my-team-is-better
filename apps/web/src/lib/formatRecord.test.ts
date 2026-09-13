import { describe, expect, it } from 'vitest'
import { formatRecord } from './formatRecord'

describe('formatRecord', () => {
  it('renders plain W-L when there are no ties, so a CFB record never grows a "-0"', () => {
    expect(formatRecord(13, 0, 0)).toBe('13-0')
  })

  it('renders W-L-T when there is at least one tie', () => {
    expect(formatRecord(6, 9, 1)).toBe('6-9-1')
  })

  it('keeps the tie count even when wins and losses are both zero', () => {
    expect(formatRecord(0, 0, 2)).toBe('0-0-2')
  })
})
