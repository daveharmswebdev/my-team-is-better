import { describe, expect, it } from 'vitest'
import {
  isPlayerLeaderSort,
  isPlayerSeasonType,
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
    expect(isPlayerLeaderSort('rushing_yards')).toBe(false)
    expect(isPlayerLeaderSort(undefined)).toBe(false)
  })
})
