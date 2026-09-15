import { describe, expect, it } from 'vitest'
import {
  CAREER_WITH_NULL_STATS,
  KURT_WARNER_CAREER,
  STEVE_MCNAIR_CAREER,
} from './playerFixtures'
import {
  compareUndercountNote,
  comparisonRows,
  formatGameDate,
  largerRecordSide,
  largerSide,
} from './playerCompare'

const record = (wins: number, losses: number, ties = 0) => ({
  wins,
  losses,
  ties,
  starts: wins + losses + ties,
})

describe('largerSide (issue #301)', () => {
  it('marks the larger number, on either side', () => {
    expect(largerSide(4044, 2179)).toBe('a')
    expect(largerSide(2179, 4044)).toBe('b')
    expect(largerSide(3, 4)).toBe('b')
  })

  it('marks the larger number even where larger is worse (interceptions)', () => {
    expect(largerSide(11, 8)).toBe('a')
  })

  it('marks nothing when the two are equal', () => {
    expect(largerSide(1, 1)).toBeNull()
    expect(largerSide(0, 0)).toBeNull()
  })

  it('marks nothing when either side is null', () => {
    expect(largerSide(null, 5)).toBeNull()
    expect(largerSide(5, null)).toBeNull()
    expect(largerSide(0, null)).toBeNull()
    expect(largerSide(null, null)).toBeNull()
  })
})

describe('largerRecordSide (issue #301)', () => {
  it('compares wins only', () => {
    expect(largerRecordSide(record(13, 3), record(9, 2))).toBe('a')
    expect(largerRecordSide(record(2, 0), record(3, 9))).toBe('b')
  })

  it('marks nothing on equal wins, whatever the losses or ties', () => {
    expect(largerRecordSide(record(3, 0), record(3, 1))).toBeNull()
    expect(largerRecordSide(record(3, 1, 1), record(3, 1))).toBeNull()
  })
})

describe('comparisonRows (issue #301)', () => {
  it('lists the rows in order, without sack rows', () => {
    const rows = comparisonRows(
      KURT_WARNER_CAREER.regular_season,
      STEVE_MCNAIR_CAREER.regular_season,
    )
    expect(rows.map((row) => row.label)).toEqual([
      'Seasons',
      'Games',
      'Starter record',
      'Completions',
      'Attempts',
      'Passing yards',
      'Passing TDs',
      'Interceptions',
      'Carries',
      'Rushing yards',
      'Rushing TDs',
    ])
  })

  it('formats each value as the API sent it and marks the larger one', () => {
    const rows = comparisonRows(
      KURT_WARNER_CAREER.regular_season,
      STEVE_MCNAIR_CAREER.regular_season,
    )
    const byLabel = Object.fromEntries(rows.map((row) => [row.label, row]))
    expect(byLabel['Passing yards']).toMatchObject({
      a: '4,044',
      b: '2,179',
      marked: 'a',
    })
    expect(byLabel['Interceptions']).toMatchObject({
      a: '11',
      b: '8',
      marked: 'a',
    })
    expect(byLabel['Carries']).toMatchObject({ a: '22', b: '72', marked: 'b' })
    expect(byLabel['Seasons']).toMatchObject({ a: '1', b: '1', marked: null })
    expect(byLabel['Starter record']).toMatchObject({
      a: '13-3',
      b: '9-2',
      marked: 'a',
    })
  })

  it('marks the playoff games row for the player with more, and not an equal-wins record', () => {
    const rows = comparisonRows(
      KURT_WARNER_CAREER.postseason,
      STEVE_MCNAIR_CAREER.postseason,
    )
    const byLabel = Object.fromEntries(rows.map((row) => [row.label, row]))
    expect(byLabel['Games']).toMatchObject({ a: '3', b: '4', marked: 'b' })
    expect(byLabel['Starter record']).toMatchObject({
      a: '3-0',
      b: '3-1',
      marked: null,
    })
  })

  it('reads a null stat as "not recorded" and leaves its row unmarked', () => {
    const rows = comparisonRows(
      KURT_WARNER_CAREER.regular_season,
      CAREER_WITH_NULL_STATS.regular_season,
    )
    const byLabel = Object.fromEntries(rows.map((row) => [row.label, row]))
    expect(byLabel['Games']).toMatchObject({
      a: '15',
      b: 'not recorded',
      marked: null,
    })
    expect(byLabel['Passing TDs']).toMatchObject({
      b: 'not recorded',
      marked: null,
    })
    // Both recorded: still marked.
    expect(byLabel['Passing yards']).toMatchObject({
      a: '4,044',
      b: '1,210',
      marked: 'a',
    })
  })

  it('gives a player with no totals of the type null values and marks nothing', () => {
    const rows = comparisonRows(
      KURT_WARNER_CAREER.postseason,
      CAREER_WITH_NULL_STATS.postseason,
    )
    expect(rows.every((row) => row.b === null)).toBe(true)
    expect(rows.every((row) => row.a !== null)).toBe(true)
    expect(rows.every((row) => row.marked === null)).toBe(true)
  })
})

describe('formatGameDate (issue #301)', () => {
  it('reads an ISO date as a calendar date, with no time zone shift', () => {
    expect(formatGameDate('1999-10-31')).toBe('Oct 31, 1999')
    expect(formatGameDate('2000-01-30')).toBe('Jan 30, 2000')
  })

  it('passes anything else through as sent', () => {
    expect(formatGameDate('sometime in October')).toBe('sometime in October')
  })
})

describe('compareUndercountNote (issue #301)', () => {
  it('names each season line of either player that undercounts games', () => {
    expect(compareUndercountNote(KURT_WARNER_CAREER, STEVE_MCNAIR_CAREER)).toBe(
      'These totals undercount games the source has no stat lines for. Kurt Warner, 1999 regular season: 1 game.',
    )
    expect(
      compareUndercountNote(STEVE_MCNAIR_CAREER, {
        ...KURT_WARNER_CAREER,
        seasons: [
          { ...KURT_WARNER_CAREER.seasons[0]!, games_without_stat_lines: 2 },
          { ...KURT_WARNER_CAREER.seasons[1]!, games_without_stat_lines: 1 },
        ],
      }),
    ).toBe(
      'These totals undercount games the source has no stat lines for. Kurt Warner, 1999 regular season: 2 games. Kurt Warner, 1999 playoffs: 1 game.',
    )
  })

  it('says nothing when no line undercounts', () => {
    expect(
      compareUndercountNote(STEVE_MCNAIR_CAREER, CAREER_WITH_NULL_STATS),
    ).toBeNull()
  })
})
