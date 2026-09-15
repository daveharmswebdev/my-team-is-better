import { describe, expect, it } from 'vitest'
import {
  CATEGORY_LABEL,
  LEADER_BOARD_COLUMNS,
  NOT_RECORDED,
  PLAYER_STATS_SOURCE_ID,
  SEASON_TYPE_LABEL,
  SORT_LABEL,
  STAT_COLUMNS,
  formatSeasonSpan,
  formatStat,
  sortForStat,
  undercountNote,
} from './playerStats'

describe('formatStat (issue #296)', () => {
  it('shows a stat the source did not track as "not recorded", never 0 and never blank', () => {
    expect(NOT_RECORDED).toBe('not recorded')
    expect(formatStat(null)).toBe('not recorded')
  })

  it('keeps a recorded zero as 0', () => {
    expect(formatStat(0)).toBe('0')
  })

  it('groups thousands and keeps the sign it was given', () => {
    expect(formatStat(4624)).toBe('4,624')
    expect(formatStat(-7)).toBe('-7')
    expect(formatStat(-1234)).toBe('-1,234')
  })
})

describe('STAT_COLUMNS', () => {
  it('lists the v1 stat columns in order, with no sack columns (#298)', () => {
    expect(STAT_COLUMNS.map((column) => column.key)).toEqual([
      'completions',
      'attempts',
      'passing_yards',
      'passing_tds',
      'passing_interceptions',
      'carries',
      'rushing_yards',
      'rushing_tds',
    ])
    for (const column of STAT_COLUMNS) {
      expect(column.label).not.toMatch(/sack/i)
    }
  })
})

describe('undercountNote', () => {
  it('names one game in the singular', () => {
    expect(undercountNote(1)).toBe(
      'Totals undercount 1 game: the source has no stat lines for it.',
    )
  })

  it('names several games in the plural', () => {
    expect(undercountNote(3)).toBe(
      'Totals undercount 3 games: the source has no stat lines for them.',
    )
  })
})

describe('formatSeasonSpan', () => {
  it('prints one season once', () => {
    expect(formatSeasonSpan(1999, 1999)).toBe('1999')
  })

  it('prints a span with an en dash', () => {
    expect(formatSeasonSpan(1999, 2023)).toBe('1999–2023')
  })
})

describe('labels', () => {
  it('labels both season types and every sort', () => {
    expect(SEASON_TYPE_LABEL).toEqual({
      regular: 'Regular season',
      postseason: 'Playoffs',
    })
    expect(SORT_LABEL).toEqual({
      passing_yards: 'passing yards',
      passing_tds: 'passing TDs',
      wins: 'starter wins',
      rushing_yards: 'rushing yards',
      rushing_tds: 'rushing TDs',
      carries: 'carries',
    })
  })

  it("selects the player credit by the API's id", () => {
    expect(PLAYER_STATS_SOURCE_ID).toBe('nflverse_player_stats')
  })

  it('names both categories for the dropdown', () => {
    expect(CATEGORY_LABEL).toEqual({ passing: 'Passing', rushing: 'Rushing' })
  })
})

/**
 * Issue #312: each board's columns, stated once. The rushing board's labels
 * are `STAT_COLUMNS`' own, so a column renamed there is renamed on both
 * boards, and which columns re-sort a board follows from the category's
 * sorts rather than a second list.
 */
describe('LEADER_BOARD_COLUMNS', () => {
  it('gives the passing board every stat column, and the record', () => {
    expect(LEADER_BOARD_COLUMNS.passing.showsRecord).toBe(true)
    expect(LEADER_BOARD_COLUMNS.passing.stats).toEqual(STAT_COLUMNS)
  })

  it('gives the rushing board its three columns and no record', () => {
    expect(LEADER_BOARD_COLUMNS.rushing.showsRecord).toBe(false)
    expect(LEADER_BOARD_COLUMNS.rushing.stats).toEqual([
      { key: 'carries', label: 'Carries' },
      { key: 'rushing_yards', label: 'Rushing yards' },
      { key: 'rushing_tds', label: 'Rushing TDs' },
    ])
  })

  it('takes the rushing labels from STAT_COLUMNS, not a copy of them', () => {
    for (const column of LEADER_BOARD_COLUMNS.rushing.stats) {
      expect(STAT_COLUMNS).toContain(column)
    }
  })
})

describe('sortForStat', () => {
  it('sorts a board only by the columns its own category sorts on', () => {
    expect(sortForStat('passing', 'passing_yards')).toBe('passing_yards')
    expect(sortForStat('passing', 'passing_tds')).toBe('passing_tds')
    expect(sortForStat('passing', 'completions')).toBeUndefined()
    // The passing board shows the rushing stats, but never sorts on them.
    expect(sortForStat('passing', 'rushing_yards')).toBeUndefined()
    expect(sortForStat('rushing', 'rushing_yards')).toBe('rushing_yards')
    expect(sortForStat('rushing', 'rushing_tds')).toBe('rushing_tds')
    expect(sortForStat('rushing', 'carries')).toBe('carries')
    expect(sortForStat('rushing', 'passing_yards')).toBeUndefined()
  })

  it('makes every column of the rushing board sortable', () => {
    for (const column of LEADER_BOARD_COLUMNS.rushing.stats) {
      expect(sortForStat('rushing', column.key)).toBe(column.key)
    }
  })
})
