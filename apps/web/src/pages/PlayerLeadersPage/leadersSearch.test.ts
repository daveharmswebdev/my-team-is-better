import { describe, expect, it } from 'vitest'
import { parseLeadersSearch, toLeadersSearch } from './leadersSearch'

describe('leaders URL state (issue #296)', () => {
  it('defaults to the regular season, by passing yards, from the top', () => {
    expect(parseLeadersSearch(new URLSearchParams(''))).toEqual({
      season_type: 'regular',
      sort: 'passing_yards',
      offset: 0,
    })
  })

  it('reads a valid season type, sort and offset', () => {
    expect(
      parseLeadersSearch(
        new URLSearchParams('season_type=postseason&sort=wins&offset=50'),
      ),
    ).toEqual({ season_type: 'postseason', sort: 'wins', offset: 50 })
  })

  it.each(['playoffs', 'Regular', ''])(
    'falls back to the regular season for season_type=%j',
    (value) => {
      expect(
        parseLeadersSearch(new URLSearchParams({ season_type: value }))
          .season_type,
      ).toBe('regular')
    },
  )

  it.each(['rushing_yards', 'WINS', ''])(
    'falls back to passing yards for sort=%j',
    (value) => {
      expect(
        parseLeadersSearch(new URLSearchParams({ sort: value })).sort,
      ).toBe('passing_yards')
    },
  )

  it.each(['-50', 'abc', '1.5', '', '1e3', ' 50', '99999999999999999999'])(
    'falls back to the top for offset=%j',
    (value) => {
      expect(
        parseLeadersSearch(new URLSearchParams({ offset: value })).offset,
      ).toBe(0)
    },
  )

  it('writes season type, sort and offset, in that order, and reads them back', () => {
    const view = {
      season_type: 'postseason',
      sort: 'passing_tds',
      offset: 100,
    } as const
    const search = toLeadersSearch(view)
    expect(search.toString()).toBe(
      'season_type=postseason&sort=passing_tds&offset=100',
    )
    expect(parseLeadersSearch(search)).toEqual(view)
  })
})
