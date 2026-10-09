import { describe, expect, it } from 'vitest'
import type { PlayerStatsOut } from './api/types'
import { UNRECORDED_STATS } from './playerFixtures'
import {
  CATEGORY_LABEL,
  DASH,
  DEFENSE_EARLY_ERA_NOTE,
  DEFENSE_UNOFFICIAL_NOTE,
  LEADER_BOARD_COLUMNS,
  LEADER_COLUMN_NOTES,
  NONE_LABEL,
  NOT_RECORDED,
  PLAYER_STATS_SOURCE_ID,
  SEASON_TYPE_LABEL,
  SORT_LABEL,
  STAT_COLUMNS,
  deriveKickingStats,
  fgPctEmptyCopy,
  fgPctNote,
  formatSeasonSpan,
  formatStat,
  leaderColumnNoteId,
  leaderColumnNotes,
  leaderStatCell,
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
      receiving_yards: 'receiving yards',
      receiving_tds: 'receiving TDs',
      receptions: 'receptions',
      fg_made: 'field goals made',
      fg_pct: 'field-goal percentage',
      fg_made_50_plus: 'field goals from 50+',
      fg_long: 'longest field goal',
      fg_att: 'field-goal attempts',
      pat_made: 'extra points made',
      pt_yards: 'punting yards',
      pt_net_yards: 'net punting yards',
      pt_att: 'punts',
      pt_inside_20: 'punts inside the 20',
      def_sacks: 'sacks',
      def_interceptions: 'interceptions',
      def_tackles_solo: 'solo tackles',
      def_fumbles_forced: 'forced fumbles',
      def_pass_defended: 'passes defended',
    })
  })

  it("selects the player credit by the API's id", () => {
    expect(PLAYER_STATS_SOURCE_ID).toBe('nflverse_player_stats')
  })

  it('names every category for the dropdown', () => {
    expect(CATEGORY_LABEL).toEqual({
      passing: 'Passing',
      rushing: 'Rushing',
      receiving: 'Receiving',
      kicking: 'Kicking',
      punting: 'Punting',
      defense: 'Defense',
    })
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

/**
 * Issue #314: the receiving board. Its columns are its own list, not a
 * filter of `STAT_COLUMNS`: the career and compare tables read
 * `STAT_COLUMNS`, and non-QB career pages are out of epic #311's scope, so
 * those tables must not gain a receiving column. `targets`, first downs and
 * fumbles lost are mirrored in the type but shown nowhere (#345).
 */
describe('the receiving board (issue #314)', () => {
  it('gives the receiving board its three columns and no record', () => {
    expect(LEADER_BOARD_COLUMNS.receiving.showsRecord).toBe(false)
    expect(LEADER_BOARD_COLUMNS.receiving.stats).toEqual([
      { key: 'receptions', label: 'Receptions' },
      { key: 'receiving_yards', label: 'Receiving yards' },
      { key: 'receiving_tds', label: 'Receiving TDs' },
    ])
  })

  it('makes every column of the receiving board sort by its own sort', () => {
    expect(sortForStat('receiving', 'receptions')).toBe('receptions')
    expect(sortForStat('receiving', 'receiving_yards')).toBe('receiving_yards')
    expect(sortForStat('receiving', 'receiving_tds')).toBe('receiving_tds')
    for (const column of LEADER_BOARD_COLUMNS.receiving.stats) {
      expect(sortForStat('receiving', column.key)).toBe(column.key)
    }
  })

  it('never sorts the receiving board by another category, nor by targets', () => {
    expect(sortForStat('receiving', 'targets')).toBeUndefined()
    expect(sortForStat('receiving', 'rushing_yards')).toBeUndefined()
    expect(sortForStat('receiving', 'carries')).toBeUndefined()
    expect(sortForStat('receiving', 'passing_yards')).toBeUndefined()
    expect(sortForStat('rushing', 'receiving_yards')).toBeUndefined()
    expect(sortForStat('passing', 'receptions')).toBeUndefined()
  })

  it('adds no receiving stat to the career and compare columns', () => {
    for (const column of STAT_COLUMNS) {
      expect(column.key).not.toMatch(/recei|target/)
    }
  })

  it('shows targets, first downs and fumbles lost on no board', () => {
    for (const board of Object.values(LEADER_BOARD_COLUMNS)) {
      for (const column of board.stats) {
        expect([
          'targets',
          'receiving_first_downs',
          'receiving_fumbles_lost',
        ]).not.toContain(column.key)
      }
    }
  })
})

/** A kicker's stats as the API sends them: every other stat a recorded 0. */
function kicker(kicking: Partial<PlayerStatsOut>): PlayerStatsOut {
  const zeros = Object.fromEntries(
    Object.keys(UNRECORDED_STATS).map((key) => [key, 0]),
  ) as unknown as PlayerStatsOut
  return { ...zeros, fg_long: null, pt_long: null, ...kicking }
}

/**
 * Issue #315: the two kicking sorts the engine computes and does not send.
 * They are the one place apps/web derives anything, so both live in one
 * function and are pinned here.
 */
describe('deriveKickingStats (issue #315)', () => {
  it('derives FG% as made over attempted, unrounded', () => {
    expect(
      deriveKickingStats(kicker({ fg_made: 36, fg_att: 38 })).fg_pct,
    ).toBeCloseTo(36 / 38, 12)
  })

  it('has no FG% for a kicker with no attempts, or a null count', () => {
    expect(deriveKickingStats(kicker({ fg_made: 0, fg_att: 0 })).fg_pct).toBe(
      null,
    )
    expect(
      deriveKickingStats(kicker({ fg_made: null, fg_att: 10 })).fg_pct,
    ).toBe(null)
    expect(
      deriveKickingStats(kicker({ fg_made: 5, fg_att: null })).fg_pct,
    ).toBe(null)
  })

  it('counts 50+ as both distance buckets, so a 60+-only kicker counts', () => {
    // Brandon Aubrey 2023: 9 from 50-59 and 1 from 60+.
    expect(
      deriveKickingStats(kicker({ fg_made_50_59: 9, fg_made_60_: 1 }))
        .fg_made_50_plus,
    ).toBe(10)
    expect(
      deriveKickingStats(kicker({ fg_made_50_59: 0, fg_made_60_: 1 }))
        .fg_made_50_plus,
    ).toBe(1)
    expect(
      deriveKickingStats(kicker({ fg_made_50_59: 0, fg_made_60_: 0 }))
        .fg_made_50_plus,
    ).toBe(0)
  })

  it('has no 50+ when either bucket is null', () => {
    expect(
      deriveKickingStats(kicker({ fg_made_50_59: null, fg_made_60_: 1 }))
        .fg_made_50_plus,
    ).toBe(null)
    expect(
      deriveKickingStats(kicker({ fg_made_50_59: 3, fg_made_60_: null }))
        .fg_made_50_plus,
    ).toBe(null)
  })
})

describe('leaderStatCell (issue #315)', () => {
  it('shows FG% to one decimal with a percent sign', () => {
    expect(
      leaderStatCell(kicker({ fg_made: 43, fg_att: 46 }), 'fg_pct'),
    ).toEqual({ kind: 'value', text: '93.5%' })
    expect(
      leaderStatCell(kicker({ fg_made: 36, fg_att: 38 }), 'fg_pct'),
    ).toEqual({ kind: 'value', text: '94.7%' })
    expect(
      leaderStatCell(kicker({ fg_made: 11, fg_att: 11 }), 'fg_pct'),
    ).toEqual({ kind: 'value', text: '100.0%' })
    expect(leaderStatCell(kicker({ fg_made: 0, fg_att: 1 }), 'fg_pct')).toEqual(
      { kind: 'value', text: '0.0%' },
    )
  })

  it('shows a dash, never 0 or "not recorded", for an FG% with no attempts or a null count', () => {
    expect(DASH).toBe('–')
    expect(NONE_LABEL).toBe('none')
    for (const stats of [
      kicker({ fg_made: 0, fg_att: 0 }),
      kicker({ fg_made: null, fg_att: 3 }),
      kicker({ fg_made: 3, fg_att: null }),
    ]) {
      expect(leaderStatCell(stats, 'fg_pct')).toEqual({ kind: 'none' })
    }
  })

  it('shows 50+ as the sum of both buckets, and "not recorded" when one is null', () => {
    expect(
      leaderStatCell(
        kicker({ fg_made_50_59: 9, fg_made_60_: 1 }),
        'fg_made_50_plus',
      ),
    ).toEqual({ kind: 'value', text: '10' })
    expect(
      leaderStatCell(
        kicker({ fg_made_50_59: null, fg_made_60_: 1 }),
        'fg_made_50_plus',
      ),
    ).toEqual({ kind: 'not-recorded' })
  })

  it('shows a null longest kick or punt as a dash: he never made one, not an unrecorded stat', () => {
    expect(leaderStatCell(kicker({ fg_long: null }), 'fg_long')).toEqual({
      kind: 'none',
    })
    expect(leaderStatCell(kicker({ pt_long: null }), 'pt_long')).toEqual({
      kind: 'none',
    })
    expect(leaderStatCell(kicker({ fg_long: 60 }), 'fg_long')).toEqual({
      kind: 'value',
      text: '60',
    })
  })

  it('keeps a recorded kicking or punting 0 as 0, groups thousands, and leaves other nulls "not recorded"', () => {
    expect(leaderStatCell(kicker({ pat_made: 0 }), 'pat_made')).toEqual({
      kind: 'value',
      text: '0',
    })
    expect(leaderStatCell(kicker({ pt_yards: 4831 }), 'pt_yards')).toEqual({
      kind: 'value',
      text: '4,831',
    })
    expect(leaderStatCell(kicker({ pt_att: null }), 'pt_att')).toEqual({
      kind: 'not-recorded',
    })
    expect(leaderStatCell(UNRECORDED_STATS, 'receiving_yards')).toEqual({
      kind: 'not-recorded',
    })
  })
})

describe('the kicking and punting boards (issue #315)', () => {
  it('gives the kicking board its six columns, derived ones included, and no record', () => {
    expect(LEADER_BOARD_COLUMNS.kicking.showsRecord).toBe(false)
    expect(LEADER_BOARD_COLUMNS.kicking.stats).toEqual([
      { key: 'fg_made', label: 'FG made' },
      { key: 'fg_att', label: 'FG att' },
      { key: 'fg_pct', label: 'FG%' },
      { key: 'fg_made_50_plus', label: '50+' },
      { key: 'fg_long', label: 'Long' },
      { key: 'pat_made', label: 'XP made' },
    ])
  })

  it('gives the punting board its four columns and no record', () => {
    expect(LEADER_BOARD_COLUMNS.punting.showsRecord).toBe(false)
    expect(LEADER_BOARD_COLUMNS.punting.stats).toEqual([
      { key: 'pt_att', label: 'Punts' },
      { key: 'pt_yards', label: 'Yards' },
      { key: 'pt_net_yards', label: 'Net yards' },
      { key: 'pt_inside_20', label: 'Inside 20' },
    ])
  })

  it('makes every kicking and punting column sort by its own sort, the derived ones included', () => {
    expect(sortForStat('kicking', 'fg_pct')).toBe('fg_pct')
    expect(sortForStat('kicking', 'fg_made_50_plus')).toBe('fg_made_50_plus')
    for (const category of ['kicking', 'punting'] as const) {
      for (const column of LEADER_BOARD_COLUMNS[category].stats) {
        expect(sortForStat(category, column.key)).toBe(column.key)
      }
    }
  })

  it('never sorts a board by another category, the derived sorts included', () => {
    expect(sortForStat('passing', 'fg_pct')).toBeUndefined()
    expect(sortForStat('punting', 'fg_made_50_plus')).toBeUndefined()
    expect(sortForStat('punting', 'fg_made')).toBeUndefined()
    expect(sortForStat('kicking', 'pt_yards')).toBeUndefined()
    expect(sortForStat('kicking', 'pat_att')).toBeUndefined()
    expect(sortForStat('kicking', 'fg_made_50_59')).toBeUndefined()
  })

  it('shows pat_att, pt_long and the raw distance buckets on no board', () => {
    for (const board of Object.values(LEADER_BOARD_COLUMNS)) {
      for (const column of board.stats) {
        expect([
          'pat_att',
          'pt_long',
          'fg_made_50_59',
          'fg_made_60_',
          'targets',
        ]).not.toContain(column.key)
      }
    }
  })

  it('adds no kicking or punting stat to the career and compare columns', () => {
    for (const column of STAT_COLUMNS) {
      expect(column.key).not.toMatch(/^(fg|pat|pt)_/)
    }
  })
})

describe('the FG% minimum, in words (issue #315)', () => {
  it('names the attempts minimum of each season type, from the mirrored constant', () => {
    expect(fgPctNote('regular')).toBe(
      'Field-goal percentage ranks only kickers with at least 100 career field-goal attempts in the regular season. Every other kicking column ranks every player with a field-goal or extra-point attempt.',
    )
    expect(fgPctNote('postseason')).toBe(
      'Field-goal percentage ranks only kickers with at least 15 career field-goal attempts in the playoffs. Every other kicking column ranks every player with a field-goal or extra-point attempt.',
    )
  })

  it('says why the FG% board is empty, not that no stats are loaded', () => {
    expect(fgPctEmptyCopy('regular')).toBe(
      'No kicker has reached 100 career field-goal attempts in the regular season, so nobody qualifies for the field-goal percentage board.',
    )
    expect(fgPctEmptyCopy('postseason')).toBe(
      'No kicker has reached 15 career field-goal attempts in the playoffs, so nobody qualifies for the field-goal percentage board.',
    )
  })
})

/**
 * Issue #317: the defense board. Its five columns are its own list, never
 * part of `STAT_COLUMNS` (career and compare pages stay QB-only, #352). Two
 * founder-required notes (#316) travel with the columns they cover, so a
 * column cannot be on a board without its note.
 */
describe('the defense board (issue #317)', () => {
  it('gives the defense board its five columns, in order, and no record', () => {
    expect(LEADER_BOARD_COLUMNS.defense.showsRecord).toBe(false)
    expect(LEADER_BOARD_COLUMNS.defense.stats).toEqual([
      { key: 'def_sacks', label: 'Sacks', note: 'early-era' },
      { key: 'def_interceptions', label: 'INT', fullLabel: 'Interceptions' },
      { key: 'def_tackles_solo', label: 'Solo tackles', note: 'unofficial' },
      {
        key: 'def_fumbles_forced',
        label: 'FF',
        fullLabel: 'Forced fumbles',
        note: 'early-era',
      },
      {
        key: 'def_pass_defended',
        label: 'PD',
        fullLabel: 'Passes defended',
        note: 'unofficial',
      },
    ])
  })

  it('makes each defense column sort by its own sort', () => {
    expect(sortForStat('defense', 'def_sacks')).toBe('def_sacks')
    expect(sortForStat('defense', 'def_interceptions')).toBe(
      'def_interceptions',
    )
    expect(sortForStat('defense', 'def_tackles_solo')).toBe('def_tackles_solo')
    expect(sortForStat('defense', 'def_fumbles_forced')).toBe(
      'def_fumbles_forced',
    )
    expect(sortForStat('defense', 'def_pass_defended')).toBe(
      'def_pass_defended',
    )
  })

  it('never sorts the defense board by another category, nor another board by defense', () => {
    expect(sortForStat('defense', 'passing_interceptions')).toBeUndefined()
    expect(sortForStat('defense', 'fg_made')).toBeUndefined()
    expect(sortForStat('passing', 'def_interceptions')).toBeUndefined()
    expect(sortForStat('kicking', 'def_sacks')).toBeUndefined()
  })

  it('shows sacks with one decimal, always: a half sack is never rounded away', () => {
    expect(leaderStatCell(kicker({ def_sacks: 17.5 }), 'def_sacks')).toEqual({
      kind: 'value',
      text: '17.5',
    })
    expect(leaderStatCell(kicker({ def_sacks: 19 }), 'def_sacks')).toEqual({
      kind: 'value',
      text: '19.0',
    })
    expect(leaderStatCell(kicker({ def_sacks: 0.5 }), 'def_sacks')).toEqual({
      kind: 'value',
      text: '0.5',
    })
    expect(leaderStatCell(kicker({ def_sacks: 0 }), 'def_sacks')).toEqual({
      kind: 'value',
      text: '0.0',
    })
    expect(leaderStatCell(kicker({ def_sacks: 138.5 }), 'def_sacks')).toEqual({
      kind: 'value',
      text: '138.5',
    })
  })

  it('shows the four counts as integers, and a recorded 0 as 0', () => {
    const stats = kicker({
      def_interceptions: 9,
      def_tackles_solo: 95,
      def_fumbles_forced: 0,
      def_pass_defended: 25,
    })
    expect(leaderStatCell(stats, 'def_interceptions')).toEqual({
      kind: 'value',
      text: '9',
    })
    expect(leaderStatCell(stats, 'def_tackles_solo')).toEqual({
      kind: 'value',
      text: '95',
    })
    expect(leaderStatCell(stats, 'def_fumbles_forced')).toEqual({
      kind: 'value',
      text: '0',
    })
    expect(leaderStatCell(stats, 'def_pass_defended')).toEqual({
      kind: 'value',
      text: '25',
    })
  })

  it('keeps a null defense stat "not recorded", never 0 or 0.0', () => {
    for (const key of [
      'def_sacks',
      'def_interceptions',
      'def_tackles_solo',
      'def_fumbles_forced',
      'def_pass_defended',
    ] as const) {
      expect(leaderStatCell(UNRECORDED_STATS, key)).toEqual({
        kind: 'not-recorded',
      })
    }
  })

  it('labels the defense category and its five sorts', () => {
    expect(CATEGORY_LABEL.defense).toBe('Defense')
    expect(SORT_LABEL.def_sacks).toBe('sacks')
    expect(SORT_LABEL.def_interceptions).toBe('interceptions')
    expect(SORT_LABEL.def_tackles_solo).toBe('solo tackles')
    expect(SORT_LABEL.def_fumbles_forced).toBe('forced fumbles')
    expect(SORT_LABEL.def_pass_defended).toBe('passes defended')
  })

  it('states both notes exactly as the founder wrote them (#316)', () => {
    expect(DEFENSE_EARLY_ERA_NOTE).toBe(
      "Sacks and forced fumbles are counted from play-by-play. For 1999-2009, that can leave a player's season 0.5 to 2 short of the official total, and we show the source's number as is.",
    )
    expect(DEFENSE_UNOFFICIAL_NOTE).toBe(
      "Solo tackles and passes defended are unofficial stats. Each team's scorers chart them, and the league doesn't keep them as official stats.",
    )
    expect(LEADER_COLUMN_NOTES['early-era'].text).toBe(DEFENSE_EARLY_ERA_NOTE)
    expect(LEADER_COLUMN_NOTES.unofficial.text).toBe(DEFENSE_UNOFFICIAL_NOTE)
    expect(LEADER_COLUMN_NOTES['early-era'].marker).not.toBe(
      LEADER_COLUMN_NOTES.unofficial.marker,
    )
  })

  it('puts both notes on the defense board, in column order, and on no other board', () => {
    expect(leaderColumnNotes('defense')).toEqual(['early-era', 'unofficial'])
    for (const category of [
      'passing',
      'rushing',
      'receiving',
      'kicking',
      'punting',
    ] as const) {
      expect(leaderColumnNotes(category)).toEqual([])
    }
  })

  it('builds each note id from the one prefix, distinct per note', () => {
    expect(leaderColumnNoteId('p', 'early-era')).toBe('p-early-era')
    expect(leaderColumnNoteId('p', 'unofficial')).toBe('p-unofficial')
  })

  it('adds no defense stat to the career and compare columns (#352)', () => {
    for (const column of STAT_COLUMNS) {
      expect(column.key).not.toMatch(/^def_/)
    }
  })
})
