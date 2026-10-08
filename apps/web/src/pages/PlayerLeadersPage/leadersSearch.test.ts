import { describe, expect, it } from 'vitest'
import {
  parseLeadersSearch,
  toLeadersSearch,
  withCategory,
} from './leadersSearch'

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

  it.each([
    'returning',
    'Kicking',
    'Rushing',
    'Receiving',
    'passing,rushing',
    '',
  ])('falls back to passing for category=%j', (value) => {
    const view = parseLeadersSearch(new URLSearchParams({ category: value }))
    expect(view.category).toBe('passing')
    expect(view.sort).toBe('passing_yards')
  })

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

/** Issue #314: the receiving board's URL, by the same rules as rushing. */
describe('the receiving category in the URL (issue #314)', () => {
  it('reads the receiving category with one of its own sorts', () => {
    expect(
      parseLeadersSearch(
        new URLSearchParams('category=receiving&sort=receptions&offset=50'),
      ),
    ).toEqual({
      category: 'receiving',
      season_type: 'regular',
      sort: 'receptions',
      offset: 50,
    })
  })

  it('round-trips category=receiving&sort=receptions', () => {
    const view = {
      category: 'receiving',
      season_type: 'regular',
      sort: 'receptions',
      offset: 0,
    } as const
    const search = toLeadersSearch(view)
    expect(search.toString()).toBe(
      'category=receiving&season_type=regular&sort=receptions&offset=0',
    )
    expect(parseLeadersSearch(search)).toEqual(view)
  })

  it('defaults a receiving URL without a sort to receiving yards', () => {
    expect(
      parseLeadersSearch(new URLSearchParams('category=receiving')).sort,
    ).toBe('receiving_yards')
  })

  it.each(['carries', 'rushing_yards', 'wins', 'passing_tds', 'targets'])(
    'falls back to receiving yards for category=receiving&sort=%s',
    (sort) => {
      expect(
        parseLeadersSearch(
          new URLSearchParams({ category: 'receiving', sort }),
        ),
      ).toEqual({
        category: 'receiving',
        season_type: 'regular',
        sort: 'receiving_yards',
        offset: 0,
      })
    },
  )

  it('falls back to the other categories defaults for a receiving sort', () => {
    expect(
      parseLeadersSearch(
        new URLSearchParams('category=rushing&sort=receptions'),
      ).sort,
    ).toBe('rushing_yards')
    expect(
      parseLeadersSearch(new URLSearchParams('sort=receiving_tds')).sort,
    ).toBe('passing_yards')
  })

  it('lands a switch to receiving on its default sort, at the top, keeping the season type', () => {
    expect(
      withCategory(
        {
          category: 'rushing',
          season_type: 'postseason',
          sort: 'carries',
          offset: 100,
        },
        'receiving',
      ),
    ).toEqual({
      category: 'receiving',
      season_type: 'postseason',
      sort: 'receiving_yards',
      offset: 0,
    })
  })
})

/** Issue #315: the kicking and punting boards' URLs, by the same rules. */
describe('the kicking and punting categories in the URL (issue #315)', () => {
  it('reads the kicking category with a derived sort of its own', () => {
    expect(
      parseLeadersSearch(
        new URLSearchParams(
          'category=kicking&season_type=postseason&sort=fg_pct&offset=0',
        ),
      ),
    ).toEqual({
      category: 'kicking',
      season_type: 'postseason',
      sort: 'fg_pct',
      offset: 0,
    })
    expect(
      parseLeadersSearch(
        new URLSearchParams('category=kicking&sort=fg_made_50_plus'),
      ).sort,
    ).toBe('fg_made_50_plus')
  })

  it('round-trips category=punting&sort=pt_inside_20', () => {
    const view = {
      category: 'punting',
      season_type: 'regular',
      sort: 'pt_inside_20',
      offset: 50,
    } as const
    const search = toLeadersSearch(view)
    expect(search.toString()).toBe(
      'category=punting&season_type=regular&sort=pt_inside_20&offset=50',
    )
    expect(parseLeadersSearch(search)).toEqual(view)
  })

  it('defaults kicking to field goals made and punting to punting yards', () => {
    expect(
      parseLeadersSearch(new URLSearchParams('category=kicking')).sort,
    ).toBe('fg_made')
    expect(
      parseLeadersSearch(new URLSearchParams('category=punting')).sort,
    ).toBe('pt_yards')
  })

  it.each(['pt_yards', 'pt_inside_20', 'pat_att', 'fg_made_50_59', 'carries'])(
    'falls back to field goals made for category=kicking&sort=%s',
    (sort) => {
      expect(
        parseLeadersSearch(new URLSearchParams({ category: 'kicking', sort })),
      ).toEqual({
        category: 'kicking',
        season_type: 'regular',
        sort: 'fg_made',
        offset: 0,
      })
    },
  )

  it.each(['fg_made', 'fg_pct', 'pt_long', 'receptions'])(
    'falls back to punting yards for category=punting&sort=%s',
    (sort) => {
      expect(
        parseLeadersSearch(new URLSearchParams({ category: 'punting', sort })),
      ).toEqual({
        category: 'punting',
        season_type: 'regular',
        sort: 'pt_yards',
        offset: 0,
      })
    },
  )

  it('falls back to the other categories defaults for a kicking sort', () => {
    expect(
      parseLeadersSearch(new URLSearchParams('category=receiving&sort=fg_pct'))
        .sort,
    ).toBe('receiving_yards')
    expect(parseLeadersSearch(new URLSearchParams('sort=fg_made')).sort).toBe(
      'passing_yards',
    )
  })

  it('lands a switch to kicking or punting on its default sort, at the top, keeping the season type', () => {
    const from = {
      category: 'receiving',
      season_type: 'postseason',
      sort: 'receptions',
      offset: 100,
    } as const
    expect(withCategory(from, 'kicking')).toEqual({
      category: 'kicking',
      season_type: 'postseason',
      sort: 'fg_made',
      offset: 0,
    })
    expect(withCategory(from, 'punting')).toEqual({
      category: 'punting',
      season_type: 'postseason',
      sort: 'pt_yards',
      offset: 0,
    })
  })
})
