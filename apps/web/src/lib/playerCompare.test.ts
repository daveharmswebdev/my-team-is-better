import { describe, expect, it } from 'vitest'
import {
  CAREER_WITH_NULL_STATS,
  EDGERRIN_JAMES,
  FRED_MCCRARY_CAREER,
  HARRISON_VS_JAMES,
  KURT_WARNER_CAREER,
  MARE_VS_GOWIN,
  STEVE_MCNAIR_CAREER,
  WARNER_VS_MCNAIR,
  ZAYNE_ANDERSON_CAREER,
} from './playerFixtures'
import {
  compareUndercountNote,
  comparisonRows,
  formatGameDate,
  headToHeadStatLine,
  largerRecordSide,
  largerSide,
} from './playerCompare'
import { DASH } from './playerStats'

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
      'Rushing first downs',
      'Rushing fumbles lost',
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

/**
 * Issue #352: the rows are the stat groups either player recorded, by the
 * career table's rule, and the starter record shows only when one of them
 * passed or started.
 */
describe('comparisonRows for non-quarterbacks (issue #352)', () => {
  it('gives a receiver and a back the rushing and receiving rows, and no passing or record row', () => {
    const rows = comparisonRows(
      HARRISON_VS_JAMES.a.regular_season,
      HARRISON_VS_JAMES.b.regular_season,
    )
    expect(rows.map((row) => row.label)).toEqual([
      'Seasons',
      'Games',
      'Carries',
      'Rushing yards',
      'Rushing TDs',
      'Rushing first downs',
      'Rushing fumbles lost',
      'Receptions',
      'Receiving yards',
      'Receiving TDs',
    ])
    const byLabel = Object.fromEntries(rows.map((row) => [row.label, row]))
    expect(byLabel['Receiving yards']).toMatchObject({
      a: '1,663',
      b: '586',
      marked: 'a',
    })
    expect(byLabel['Rushing first downs']).toMatchObject({
      a: '0',
      b: '80',
      marked: 'b',
    })
  })

  it('gives a kicker and a punter the kicking and punting rows, a missing longest field goal as a dash, unmarked', () => {
    const rows = comparisonRows(
      MARE_VS_GOWIN.a.regular_season,
      MARE_VS_GOWIN.b.regular_season,
    )
    expect(rows.map((row) => row.label)).toEqual([
      'Seasons',
      'Games',
      'FG made',
      'FG att',
      'FG long',
      'XP made',
      'Punts',
      'Punt yards',
      'Net punt yards',
      'Inside 20',
    ])
    const byLabel = Object.fromEntries(rows.map((row) => [row.label, row]))
    expect(byLabel['FG long']).toMatchObject({ a: '54', b: DASH, marked: null })
    expect(byLabel['Punts']).toMatchObject({ a: '1', b: '81', marked: 'b' })
  })

  it("shows a tackles-only defender's solo tackles next to a quarterback (round 3)", () => {
    const rows = comparisonRows(
      KURT_WARNER_CAREER.regular_season,
      ZAYNE_ANDERSON_CAREER.regular_season,
    )
    const byLabel = Object.fromEntries(rows.map((row) => [row.label, row]))
    expect(byLabel['Solo tackles']).toMatchObject({
      a: '1',
      b: '3',
      marked: 'b',
    })
    expect(byLabel['Passing yards']).toBeDefined()
  })

  it('gives a receiver with solo tackles no defense rows next to a quarterback', () => {
    const rows = comparisonRows(
      KURT_WARNER_CAREER.regular_season,
      FRED_MCCRARY_CAREER.regular_season,
    )
    const labels = rows.map((row) => row.label)
    expect(labels).toContain('Receptions')
    expect(labels).not.toContain('Solo tackles')
  })

  it('shows no defense rows for two quarterbacks with a stray tackle each', () => {
    const rows = comparisonRows(
      KURT_WARNER_CAREER.regular_season,
      STEVE_MCNAIR_CAREER.regular_season,
    )
    expect(KURT_WARNER_CAREER.regular_season!.stats.def_tackles_solo).toBe(1)
    expect(STEVE_MCNAIR_CAREER.regular_season!.stats.def_tackles_solo).toBe(1)
    expect(rows.map((row) => row.label)).not.toContain('Solo tackles')
  })

  it('keeps the rows of the player who has totals when the other has none', () => {
    const rows = comparisonRows(MARE_VS_GOWIN.a.postseason, null)
    expect(rows.map((row) => row.label)).toEqual([
      'Seasons',
      'Games',
      'FG made',
      'FG att',
      'FG long',
      'XP made',
    ])
  })
})

describe('headToHeadStatLine (issue #352)', () => {
  const game = WARNER_VS_MCNAIR.regular_season_head_to_head.games[0]!

  it("gives a starter's passing line, then his rushing when he ran the ball", () => {
    expect(headToHeadStatLine('Kurt Warner', game.a_stats)).toBe(
      'Kurt Warner: 328 passing yards, 3 TDs, 0 INTs; 2 carries, 22 rushing yards, 0 rushing TDs',
    )
  })

  it('leaves out a group he recorded nothing in', () => {
    expect(
      headToHeadStatLine('Kurt Warner', {
        ...game.a_stats!,
        carries: 0,
        rushing_yards: 0,
        rushing_tds: 0,
        rushing_first_downs: 0,
        rushing_fumbles_lost: 0,
      }),
    ).toBe('Kurt Warner: 328 passing yards, 3 TDs, 0 INTs')
  })

  it('gives a starter who never threw a pass his rushing and receiving lines, and no passing', () => {
    expect(
      headToHeadStatLine('Wildcat Starter', {
        ...EDGERRIN_JAMES.stats,
        carries: 18,
        rushing_yards: 97,
        rushing_tds: 1,
        receptions: 1,
        receiving_yards: 12,
        receiving_tds: 0,
      }),
    ).toBe(
      'Wildcat Starter: 18 carries, 97 rushing yards, 1 rushing TD; 1 reception, 12 receiving yards, 0 receiving TDs',
    )
  })

  it('reads no stat line at all, and a stat the source did not track, as "not recorded"', () => {
    expect(headToHeadStatLine('Kurt Warner', null)).toBe(
      'Kurt Warner: not recorded',
    )
    expect(
      headToHeadStatLine('Steve McNair', {
        ...game.b_stats!,
        passing_tds: null,
      }),
    ).toBe(
      'Steve McNair: 186 passing yards, TDs not recorded, 0 INTs; 12 carries, 36 rushing yards, 1 rushing TD',
    )
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
