import { describe, expect, it } from 'vitest'
import {
  NOT_RECORDED,
  PLAYER_STATS_SOURCE_ID,
  SEASON_TYPE_LABEL,
  SORT_LABEL,
  STAT_COLUMNS,
  formatSeasonSpan,
  formatStat,
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
    })
  })

  it("selects the player credit by the API's id", () => {
    expect(PLAYER_STATS_SOURCE_ID).toBe('nflverse_player_stats')
  })
})
