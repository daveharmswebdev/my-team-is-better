import { describe, expect, it } from 'vitest'
import {
  CAREER_WITH_NULL_STATS,
  EDGERRIN_JAMES,
  FAULK_VS_FARMER,
  FRANK_WYCHECK_CAREER,
  FRED_MCCRARY_CAREER,
  HILL_VS_LAMB,
  HARRISON_VS_JAMES,
  KURT_WARNER_CAREER,
  MARE_VS_GOWIN,
  SMITH_VS_PETERSON,
  STEVE_MCNAIR_CAREER,
  WARNER_VS_MCNAIR,
  ZAYNE_ANDERSON_CAREER,
} from './playerFixtures'
import {
  MEASURED_POSITION_LABELS,
  POSITION_NOUNS,
  compareUndercountNote,
  comparisonGroup,
  comparisonRows,
  comparisonShowsRecord,
  formatGameDate,
  groupSingular,
  headToHeadStatLine,
  largerRecordSide,
  largerSide,
  notComparableCopy,
  positionPlural,
  positionSingular,
  restrictionCopy,
  showsHeadToHead,
  uncomparableCopy,
} from './playerCompare'
import type { PlayerCareerOut, PlayerCareerTotalsOut } from './api/types'
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
      'QB',
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
      'QB',
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
      'QB',
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
      comparisonGroup(KURT_WARNER_CAREER, CAREER_WITH_NULL_STATS),
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
      comparisonGroup(KURT_WARNER_CAREER, CAREER_WITH_NULL_STATS),
    )
    expect(rows.every((row) => row.b === null)).toBe(true)
    expect(rows.every((row) => row.a !== null)).toBe(true)
    expect(rows.every((row) => row.marked === null)).toBe(true)
  })
})

/**
 * Issue #352: with no position group the two players share, the rows are
 * the stat groups either player recorded, by the career table's rule, and
 * the starter record shows only when one of them passed or started. Since
 * #436 the page never shows such a pair; the rule keeps `comparisonRows`
 * total.
 */
describe('comparisonRows with no shared group (issue #352)', () => {
  it('gives a receiver and a back the rushing and receiving rows, and no passing or record row', () => {
    const rows = comparisonRows(
      HARRISON_VS_JAMES.a.regular_season,
      HARRISON_VS_JAMES.b.regular_season,
      comparisonGroup(HARRISON_VS_JAMES.a, HARRISON_VS_JAMES.b),
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
      comparisonGroup(MARE_VS_GOWIN.a, MARE_VS_GOWIN.b),
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
      comparisonGroup(KURT_WARNER_CAREER, ZAYNE_ANDERSON_CAREER),
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
      comparisonGroup(KURT_WARNER_CAREER, FRED_MCCRARY_CAREER),
    )
    const labels = rows.map((row) => row.label)
    expect(labels).toContain('Receptions')
    expect(labels).not.toContain('Solo tackles')
  })

  it('shows no defense rows for two quarterbacks with a stray tackle each', () => {
    const rows = comparisonRows(
      KURT_WARNER_CAREER.regular_season,
      STEVE_MCNAIR_CAREER.regular_season,
      'QB',
    )
    expect(KURT_WARNER_CAREER.regular_season!.stats.def_tackles_solo).toBe(1)
    expect(STEVE_MCNAIR_CAREER.regular_season!.stats.def_tackles_solo).toBe(1)
    expect(rows.map((row) => row.label)).not.toContain('Solo tackles')
  })

  it('keeps the rows of the player who has totals when the other has none', () => {
    const rows = comparisonRows(MARE_VS_GOWIN.a.postseason, null, null)
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

/**
 * Issue #438 (founder decision, 2026-10-25): the position group both
 * players share decides the rows, not whichever stats either recorded.
 * Stats outside the group are hidden.
 */
describe('comparisonRows by position group (issue #438)', () => {
  const RUSHING_ROWS = [
    'Carries',
    'Rushing yards',
    'Rushing TDs',
    'Rushing first downs',
    'Rushing fumbles lost',
  ]
  const RECEIVING_ROWS = ['Receptions', 'Receiving yards', 'Receiving TDs']

  it("gives two backs rushing then receiving, and none of Emmitt Smith's one pass or a record row", () => {
    const { a: smith, b: peterson } = SMITH_VS_PETERSON
    expect(smith.regular_season!.stats.completions).toBe(1)
    const rows = comparisonRows(
      smith.regular_season,
      peterson.regular_season,
      comparisonGroup(smith, peterson),
    )
    expect(rows.map((row) => row.label)).toEqual([
      'Seasons',
      'Games',
      ...RUSHING_ROWS,
      ...RECEIVING_ROWS,
    ])
    const byLabel = Object.fromEntries(rows.map((row) => [row.label, row]))
    expect(byLabel['Rushing yards']).toMatchObject({
      a: '5,789',
      b: '14,921',
      marked: 'b',
    })
  })

  it('gives two backs the same rows in the playoffs', () => {
    const { a: smith, b: peterson } = SMITH_VS_PETERSON
    const rows = comparisonRows(smith.postseason, peterson.postseason, 'RB')
    expect(rows.map((row) => row.label)).toEqual([
      'Seasons',
      'Games',
      ...RUSHING_ROWS,
      ...RECEIVING_ROWS,
    ])
  })

  it("hides a back's solo tackles too", () => {
    const { a: faulk, b: farmer } = FAULK_VS_FARMER
    const labels = comparisonRows(
      faulk.regular_season,
      farmer.regular_season,
      comparisonGroup(faulk, farmer),
    ).map((row) => row.label)
    expect(labels).not.toContain('Solo tackles')
    expect(labels).not.toContain('Attempts')
    expect(labels).not.toContain('Starter record')
  })

  it('gives two quarterbacks the record, passing and rushing rows even when neither ran', () => {
    const noRushing = (
      totals: PlayerCareerTotalsOut,
    ): PlayerCareerTotalsOut => ({
      ...totals,
      stats: {
        ...totals.stats,
        carries: 0,
        rushing_yards: 0,
        rushing_tds: 0,
        rushing_first_downs: 0,
        rushing_fumbles_lost: 0,
      },
    })
    const rows = comparisonRows(
      noRushing(KURT_WARNER_CAREER.regular_season!),
      noRushing(STEVE_MCNAIR_CAREER.regular_season!),
      comparisonGroup(KURT_WARNER_CAREER, STEVE_MCNAIR_CAREER),
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
      ...RUSHING_ROWS,
    ])
    const byLabel = Object.fromEntries(rows.map((row) => [row.label, row]))
    expect(byLabel['Carries']).toMatchObject({ a: '0', b: '0', marked: null })
  })

  it('gives two receivers receiving only, not their carries', () => {
    const { a: hill, b: lamb } = HILL_VS_LAMB
    expect(lamb.regular_season!.stats.carries).toBeGreaterThan(0)
    const rows = comparisonRows(
      hill.regular_season,
      lamb.regular_season,
      comparisonGroup(hill, lamb),
    )
    expect(rows.map((row) => row.label)).toEqual([
      'Seasons',
      'Games',
      ...RECEIVING_ROWS,
    ])
  })

  it("gives two tight ends receiving only, not Frank Wycheck's touchdown pass", () => {
    const other: PlayerCareerOut = {
      ...FRANK_WYCHECK_CAREER,
      player_id: 1,
      display_name: 'Another tight end',
    }
    expect(FRANK_WYCHECK_CAREER.regular_season!.stats.passing_tds).toBe(1)
    const rows = comparisonRows(
      FRANK_WYCHECK_CAREER.regular_season,
      other.regular_season,
      comparisonGroup(FRANK_WYCHECK_CAREER, other),
    )
    expect(rows.map((row) => row.label)).toEqual([
      'Seasons',
      'Games',
      ...RECEIVING_ROWS,
    ])
  })

  it("keeps a group's rows for the one player with totals when the other has none", () => {
    const rows = comparisonRows(SMITH_VS_PETERSON.a.postseason, null, 'RB')
    expect(rows.map((row) => row.label)).toEqual([
      'Seasons',
      'Games',
      ...RUSHING_ROWS,
      ...RECEIVING_ROWS,
    ])
    expect(rows.every((row) => row.b === null)).toBe(true)
  })
})

describe('comparisonGroup (issue #438)', () => {
  it('is the group both players share', () => {
    expect(comparisonGroup(SMITH_VS_PETERSON.a, SMITH_VS_PETERSON.b)).toBe('RB')
    expect(comparisonGroup(KURT_WARNER_CAREER, STEVE_MCNAIR_CAREER)).toBe('QB')
  })

  it('is null for two groups, or a player with none', () => {
    expect(comparisonGroup(HARRISON_VS_JAMES.a, HARRISON_VS_JAMES.b)).toBeNull()
    expect(
      comparisonGroup(KURT_WARNER_CAREER, ZAYNE_ANDERSON_CAREER),
    ).toBeNull()
    expect(comparisonGroup(MARE_VS_GOWIN.a, MARE_VS_GOWIN.b)).toBeNull()
  })
})

describe('comparisonShowsRecord (issue #438)', () => {
  it('is true for two quarterbacks only, among grouped pairs', () => {
    expect(comparisonShowsRecord(KURT_WARNER_CAREER, STEVE_MCNAIR_CAREER)).toBe(
      true,
    )
    expect(
      comparisonShowsRecord(SMITH_VS_PETERSON.a, SMITH_VS_PETERSON.b),
    ).toBe(false)
    expect(
      comparisonShowsRecord(FRANK_WYCHECK_CAREER, FRANK_WYCHECK_CAREER),
    ).toBe(false)
  })

  it('keeps the recorded-stats rule (#352) for a pair with no shared group', () => {
    expect(
      comparisonShowsRecord(KURT_WARNER_CAREER, ZAYNE_ANDERSON_CAREER),
    ).toBe(true)
    expect(
      comparisonShowsRecord(HARRISON_VS_JAMES.a, HARRISON_VS_JAMES.b),
    ).toBe(false)
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

describe('comparing like with like (issue #436)', () => {
  it('names the restriction for each group, plural then singular', () => {
    expect(restrictionCopy('QB')).toBe(
      'Comparing quarterbacks. Player B has to be a quarterback too.',
    )
    expect(restrictionCopy('RB')).toBe(
      'Comparing running backs. Player B has to be a running back too.',
    )
    expect(restrictionCopy('WR')).toBe(
      'Comparing receivers. Player B has to be a receiver too.',
    )
    expect(restrictionCopy('TE')).toBe(
      'Comparing tight ends. Player B has to be a tight end too.',
    )
  })

  it("refuses a mixed pair in the narrator's voice: A's group, B's, then A's again", () => {
    expect(notComparableCopy('QB', groupSingular('RB'))).toBe(
      "A quarterback and a running back? That's apples and footballs, pal. Pick another quarterback.",
    )
    expect(notComparableCopy('WR', groupSingular('TE'))).toBe(
      "A receiver and a tight end? That's apples and footballs, pal. Pick another receiver.",
    )
  })

  it("fills a group-less B's slot from B's position label, never a group it lacks", () => {
    expect(notComparableCopy('QB', positionSingular('SAF'))).toBe(
      "A quarterback and a safety? That's apples and footballs, pal. Pick another quarterback.",
    )
    expect(positionSingular('OT')).toBe('an offensive tackle')
    expect(positionSingular(null)).toBe('a player at that position')
    expect(positionSingular('HB')).toBe('a player at that position')
  })

  it("says a group-less Player A's position can't be compared yet, pluralized", () => {
    expect(uncomparableCopy('K')).toBe(
      "Can't stack up kickers yet. Quarterbacks, running backs, receivers and tight ends only, for now.",
    )
    expect(uncomparableCopy('SAF')).toBe(
      "Can't stack up safeties yet. Quarterbacks, running backs, receivers and tight ends only, for now.",
    )
    expect(uncomparableCopy(null)).toBe(
      "Can't stack up players at that position yet. Quarterbacks, running backs, receivers and tight ends only, for now.",
    )
    expect(uncomparableCopy('XX')).toBe(
      "Can't stack up players at that position yet. Quarterbacks, running backs, receivers and tight ends only, for now.",
    )
  })

  it('has its own singular and plural for every measured position label (25)', () => {
    const measured =
      'WR LB RB DB DE OT TE G DT CB QB C OLB K P SAF S FS NT FB ILB MLB LS OL DL'.split(
        ' ',
      )
    expect(measured).toHaveLength(25)
    expect([...MEASURED_POSITION_LABELS].sort()).toEqual([...measured].sort())
    expect(Object.keys(POSITION_NOUNS).sort()).toEqual([...measured].sort())
    for (const label of measured) {
      const singular = positionSingular(label)
      const plural = positionPlural(label)
      expect({ label, singular }).not.toEqual({
        label,
        singular: 'a player at that position',
      })
      expect({ label, plural }).not.toEqual({
        label,
        plural: 'players at that position',
      })
      expect(singular).toMatch(/^(a|an) [a-z]/)
    }
    // A grouped label reads the same as its group.
    expect(positionPlural('QB')).toBe('quarterbacks')
    expect(positionPlural('WR')).toBe('receivers')
    expect(positionPlural('FB')).toBe('fullbacks')
  })

  it('shows head-to-head only for two quarterbacks', () => {
    expect(showsHeadToHead(WARNER_VS_MCNAIR)).toBe(true)
    expect(showsHeadToHead(HILL_VS_LAMB)).toBe(false)
    expect(showsHeadToHead(FAULK_VS_FARMER)).toBe(false)
    expect(
      showsHeadToHead({
        ...WARNER_VS_MCNAIR,
        b: { ...STEVE_MCNAIR_CAREER, group: null },
      }),
    ).toBe(false)
  })
})

describe('comparisonRows with coverage (founder rule, #448)', () => {
  it('marks no total when either side is cut off, and reads the slice in the seasons row', () => {
    const { a: faulk, b: farmer } = FAULK_VS_FARMER
    const rows = comparisonRows(
      farmer.regular_season,
      faulk.regular_season,
      'RB',
      { a: farmer.coverage, b: faulk.coverage },
    )
    expect(rows.every((row) => row.marked === null)).toBe(true)
    expect(rows[0]).toMatchObject({
      key: 'seasons',
      a: '1',
      b: '1 of 13 (1999)',
    })
    // Without coverage the same pair carries marks: the rule removed them.
    expect(
      comparisonRows(farmer.regular_season, faulk.regular_season, 'RB').some(
        (row) => row.marked !== null,
      ),
    ).toBe(true)
  })

  it('marks no playoff total either, and keeps the playoff seasons count plain', () => {
    const rows = comparisonRows(
      KURT_WARNER_CAREER.postseason,
      STEVE_MCNAIR_CAREER.postseason,
      'QB',
      { a: KURT_WARNER_CAREER.coverage, b: STEVE_MCNAIR_CAREER.coverage },
    )
    expect(rows.every((row) => row.marked === null)).toBe(true)
    expect(rows[0]).toMatchObject({ a: '1', b: '1' })
  })

  it('keeps the marks for careers that only run past the data', () => {
    const { a: hill, b: lamb } = HILL_VS_LAMB
    const rows = comparisonRows(
      hill.regular_season,
      lamb.regular_season,
      'WR',
      { a: hill.coverage, b: lamb.coverage },
    )
    expect(rows).toEqual(
      comparisonRows(hill.regular_season, lamb.regular_season, 'WR'),
    )
    expect(rows.some((row) => row.marked !== null)).toBe(true)
  })
})
