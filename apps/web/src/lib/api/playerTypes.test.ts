import { describe, expect, it } from 'vitest'
import {
  PLAYER_LEADER_CATEGORIES,
  PLAYER_LEADER_FG_PCT_MIN_ATTEMPTS,
  PLAYER_LEADER_SORTS,
  PLAYER_LEADER_SORTS_BY_CATEGORY,
  defaultSortFor,
  isPlayerLeaderCategory,
  isPlayerLeaderSort,
  isPlayerSeasonType,
  isSortInCategory,
  isUnknownPlayerErrorBody,
} from './types'

describe('isUnknownPlayerErrorBody (issue #296)', () => {
  it('accepts the API body for every published sport', () => {
    for (const sport of ['cfb', 'nfl']) {
      expect(
        isUnknownPlayerErrorBody({
          error: 'unknown_player',
          player_id: 2044124519,
          sport,
        }),
      ).toBe(true)
    }
  })

  it.each([
    ['null', null],
    ['a string', 'unknown_player'],
    ['another error', { error: 'unknown_team', player_id: 1, sport: 'nfl' }],
    ['a string id', { error: 'unknown_player', player_id: '1', sport: 'nfl' }],
    ['no id', { error: 'unknown_player', sport: 'nfl' }],
    [
      'an unpublished sport',
      { error: 'unknown_player', player_id: 1, sport: 'nba' },
    ],
    ['no sport', { error: 'unknown_player', player_id: 1 }],
  ])('rejects %s', (_name, value) => {
    expect(isUnknownPlayerErrorBody(value)).toBe(false)
  })
})

describe('player vocabularies', () => {
  it('knows exactly the season types and sorts the API accepts', () => {
    expect(isPlayerSeasonType('regular')).toBe(true)
    expect(isPlayerSeasonType('postseason')).toBe(true)
    expect(isPlayerSeasonType('playoffs')).toBe(false)
    expect(isPlayerSeasonType(null)).toBe(false)
    expect(isPlayerLeaderSort('passing_yards')).toBe(true)
    expect(isPlayerLeaderSort('passing_tds')).toBe(true)
    expect(isPlayerLeaderSort('wins')).toBe(true)
    // Rushing sorts joined the vocabulary with the rushing board (#312).
    expect(isPlayerLeaderSort('rushing_yards')).toBe(true)
    expect(isPlayerLeaderSort('rushing_tds')).toBe(true)
    expect(isPlayerLeaderSort('carries')).toBe(true)
    // Receiving sorts joined with the receiving board (#314); targets is
    // published but never a sort.
    expect(isPlayerLeaderSort('receiving_yards')).toBe(true)
    expect(isPlayerLeaderSort('receiving_tds')).toBe(true)
    expect(isPlayerLeaderSort('receptions')).toBe(true)
    expect(isPlayerLeaderSort('targets')).toBe(false)
    expect(isPlayerLeaderSort('receiving_first_downs')).toBe(false)
    // Kicking and punting sorts joined with their boards (#315). fg_pct and
    // fg_made_50_plus are sorts the engine computes, not stats it sends;
    // pat_att and pt_long are sent but never sorts.
    for (const sort of [
      'fg_made',
      'fg_pct',
      'fg_made_50_plus',
      'fg_long',
      'fg_att',
      'pat_made',
      'pt_yards',
      'pt_net_yards',
      'pt_att',
      'pt_inside_20',
    ]) {
      expect(isPlayerLeaderSort(sort)).toBe(true)
    }
    // The five defense sorts joined with their board (#317), each the stat
    // of the same name. The EPA columns are stored but never published.
    for (const sort of [
      'def_sacks',
      'def_interceptions',
      'def_tackles_solo',
      'def_fumbles_forced',
      'def_pass_defended',
    ]) {
      expect(isPlayerLeaderSort(sort)).toBe(true)
    }
    expect(isPlayerLeaderSort('def_tackles_assist')).toBe(false)
    expect(isPlayerLeaderSort('pat_att')).toBe(false)
    expect(isPlayerLeaderSort('pt_long')).toBe(false)
    expect(isPlayerLeaderSort('fg_made_50_59')).toBe(false)
    expect(isPlayerLeaderSort(undefined)).toBe(false)
  })
})

/**
 * Issue #312: the mirror of the engine's `PLAYER_LEADER_SORTS_BY_CATEGORY`.
 * The API answers a category/sort pair from two categories with a 422, so
 * these are what a caller pairs them by -- never a string check of its own.
 */
describe('leaderboard categories', () => {
  it('knows exactly the categories the API accepts', () => {
    expect(isPlayerLeaderCategory('passing')).toBe(true)
    expect(isPlayerLeaderCategory('rushing')).toBe(true)
    expect(isPlayerLeaderCategory('receiving')).toBe(true)
    expect(isPlayerLeaderCategory('kicking')).toBe(true)
    expect(isPlayerLeaderCategory('punting')).toBe(true)
    expect(isPlayerLeaderCategory('defense')).toBe(true)
    expect(isPlayerLeaderCategory('Defense')).toBe(false)
    expect(isPlayerLeaderCategory('Rushing')).toBe(false)
    expect(isPlayerLeaderCategory('Kicking')).toBe(false)
    expect(isPlayerLeaderCategory('returning')).toBe(false)
    expect(isPlayerLeaderCategory(null)).toBe(false)
    expect(PLAYER_LEADER_CATEGORIES).toEqual([
      'passing',
      'rushing',
      'receiving',
      'kicking',
      'punting',
      'defense',
    ])
  })

  it('mirrors the engine sorts of each category, its default first', () => {
    expect(PLAYER_LEADER_SORTS_BY_CATEGORY).toEqual({
      passing: ['passing_yards', 'passing_tds', 'wins'],
      rushing: ['rushing_yards', 'rushing_tds', 'carries'],
      receiving: ['receiving_yards', 'receiving_tds', 'receptions'],
      kicking: [
        'fg_made',
        'fg_pct',
        'fg_made_50_plus',
        'fg_long',
        'fg_att',
        'pat_made',
      ],
      punting: ['pt_yards', 'pt_net_yards', 'pt_att', 'pt_inside_20'],
      defense: [
        'def_sacks',
        'def_interceptions',
        'def_tackles_solo',
        'def_fumbles_forced',
        'def_pass_defended',
      ],
    })
    expect(defaultSortFor('defense')).toBe('def_sacks')
    expect(defaultSortFor('passing')).toBe('passing_yards')
    expect(defaultSortFor('rushing')).toBe('rushing_yards')
    expect(defaultSortFor('receiving')).toBe('receiving_yards')
    expect(defaultSortFor('kicking')).toBe('fg_made')
    expect(defaultSortFor('punting')).toBe('pt_yards')
  })

  it('gives every sort exactly one category, and covers them all', () => {
    for (const sort of PLAYER_LEADER_SORTS) {
      const owners = PLAYER_LEADER_CATEGORIES.filter((category) =>
        isSortInCategory(category, sort),
      )
      expect(owners).toHaveLength(1)
    }
    expect(PLAYER_LEADER_SORTS).toHaveLength(24)
  })

  it('refuses a sort from another category', () => {
    expect(isSortInCategory('receiving', 'carries')).toBe(false)
    expect(isSortInCategory('receiving', 'targets')).toBe(false)
    expect(isSortInCategory('rushing', 'receptions')).toBe(false)
    expect(isSortInCategory('receiving', 'receptions')).toBe(true)
    expect(isSortInCategory('rushing', 'wins')).toBe(false)
    expect(isSortInCategory('rushing', 'passing_yards')).toBe(false)
    expect(isSortInCategory('passing', 'rushing_tds')).toBe(false)
    expect(isSortInCategory('passing', 'nonsense')).toBe(false)
    expect(isSortInCategory('rushing', 'carries')).toBe(true)
    // #315: a punting sort is not a kicking one, nor the other way round.
    expect(isSortInCategory('kicking', 'pt_yards')).toBe(false)
    expect(isSortInCategory('punting', 'fg_made')).toBe(false)
    expect(isSortInCategory('kicking', 'pat_att')).toBe(false)
    expect(isSortInCategory('kicking', 'fg_pct')).toBe(true)
    expect(isSortInCategory('punting', 'pt_inside_20')).toBe(true)
    // #317: the defense sorts are the defense board's alone.
    expect(isSortInCategory('defense', 'def_pass_defended')).toBe(true)
    expect(isSortInCategory('defense', 'passing_interceptions')).toBe(false)
    expect(isSortInCategory('passing', 'def_interceptions')).toBe(false)
  })

  it("mirrors the engine's FG% attempts minimum per season type (#315)", () => {
    expect(PLAYER_LEADER_FG_PCT_MIN_ATTEMPTS).toEqual({
      regular: 100,
      postseason: 15,
    })
  })
})
