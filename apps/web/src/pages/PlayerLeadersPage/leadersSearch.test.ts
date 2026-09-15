import { describe, expect, it } from 'vitest'
import { parseLeadersSearch, toLeadersSearch } from './leadersSearch'

describe('leaders URL state (issue #296)', () => {
  it('defaults to passing, the regular season, by passing yards, from the top', () => {
    expect(parseLeadersSearch(new URLSearchParams(''))).toEqual({
      category: 'passing',
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
    ).toEqual({
      category: 'passing',
      season_type: 'postseason',
      sort: 'wins',
      offset: 50,
    })
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

  it('writes category, season type, sort and offset, in that order, and reads them back', () => {
    const view = {
      category: 'passing',
      season_type: 'postseason',
      sort: 'passing_tds',
      offset: 100,
    } as const
    const search = toLeadersSearch(view)
    expect(search.toString()).toBe(
      'category=passing&season_type=postseason&sort=passing_tds&offset=100',
    )
    expect(parseLeadersSearch(search)).toEqual(view)
  })
})

/**
 * Issue #312: the stat category joins the URL. It is written first, so the
 * existing `season_type=...&sort=...&offset=...` tail is unchanged, and the
 * sort is only ever one the category owns -- the API 422s a mismatched pair,
 * so the page must never send one.
 */
describe('the stat category in the URL (issue #312)', () => {
  it('reads the rushing category with one of its own sorts', () => {
    expect(
      parseLeadersSearch(
        new URLSearchParams('category=rushing&sort=carries&offset=50'),
      ),
    ).toEqual({
      category: 'rushing',
      season_type: 'regular',
      sort: 'carries',
      offset: 50,
    })
  })

  it('reads an old URL with no category at all as passing', () => {
    expect(
      parseLeadersSearch(
        new URLSearchParams('season_type=postseason&sort=wins&offset=0'),
      ),
    ).toEqual({
      category: 'passing',
      season_type: 'postseason',
      sort: 'wins',
      offset: 0,
    })
  })

  it.each(['receiving', 'Rushing', 'passing,rushing', ''])(
    'falls back to passing for category=%j',
    (value) => {
      const view = parseLeadersSearch(new URLSearchParams({ category: value }))
      expect(view.category).toBe('passing')
      expect(view.sort).toBe('passing_yards')
    },
  )

  it('falls back to the category default for a sort from another category', () => {
    expect(
      parseLeadersSearch(
        new URLSearchParams('category=rushing&sort=passing_yards'),
      ).sort,
    ).toBe('rushing_yards')
    expect(
      parseLeadersSearch(new URLSearchParams('category=rushing&sort=wins'))
        .sort,
    ).toBe('rushing_yards')
    expect(
      parseLeadersSearch(
        new URLSearchParams('category=passing&sort=rushing_tds'),
      ).sort,
    ).toBe('passing_yards')
  })

  it('defaults a category given without a sort to that category first sort', () => {
    expect(
      parseLeadersSearch(new URLSearchParams('category=rushing')).sort,
    ).toBe('rushing_yards')
  })

  it('writes the category before the season type, and reads it back', () => {
    const view = {
      category: 'rushing',
      season_type: 'postseason',
      sort: 'rushing_tds',
      offset: 0,
    } as const
    const search = toLeadersSearch(view)
    expect(search.toString()).toBe(
      'category=rushing&season_type=postseason&sort=rushing_tds&offset=0',
    )
    expect(parseLeadersSearch(search)).toEqual(view)
  })
})
