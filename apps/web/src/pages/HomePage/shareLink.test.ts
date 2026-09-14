import { describe, expect, it } from 'vitest'
import type { QuestionSubmission } from '../../components/QuestionForm/QuestionForm'
import { fromShareSearch, toShareSearch } from './shareLink'

/** A valid compare link, edited one param at a time by the rejection cases. */
const VALID_COMPARE: Record<string, string> = {
  q: 'compare',
  sport: 'cfb',
  year: '2023',
  engine: 'elo',
  a: 'Georgia',
  b: 'Michigan',
  for: 'Georgia',
}

function searchWith(overrides: Record<string, string | null>): string {
  const params = new URLSearchParams(VALID_COMPARE)
  for (const [key, value] of Object.entries(overrides)) {
    if (value === null) {
      params.delete(key)
    } else {
      params.set(key, value)
    }
  }
  return params.toString()
}

describe('toShareSearch / fromShareSearch (issue #184)', () => {
  describe('round-trips every question type, on every displayed engine', () => {
    const submissions: QuestionSubmission[] = [
      {
        questionType: 'champion',
        year: 2005,
        userTeam: 'Texas',
        sport: 'cfb',
        method: 'keener',
      },
      {
        questionType: 'champion',
        year: 2018,
        userTeam: null,
        sport: 'nfl',
        method: 'elo',
      },
      {
        questionType: 'team_case',
        year: 2010,
        team: 'Auburn',
        userTeam: 'Alabama',
        sport: 'cfb',
        method: 'elo',
      },
      {
        questionType: 'team_case',
        year: 2010,
        team: 'Auburn',
        userTeam: null,
        sport: 'cfb',
        method: 'keener',
      },
      {
        questionType: 'compare',
        year: 2023,
        teamA: 'Georgia',
        teamB: 'Michigan',
        userTeam: 'Georgia',
        sport: 'cfb',
        method: 'elo',
      },
      {
        questionType: 'compare',
        year: 2022,
        teamA: 'Kansas City Chiefs',
        teamB: 'Philadelphia Eagles',
        userTeam: null,
        sport: 'nfl',
        method: 'keener',
      },
    ]

    it.each(submissions)(
      '$questionType ($sport, $method, userTeam $userTeam)',
      (submission) => {
        expect(fromShareSearch(toShareSearch(submission))).toEqual(submission)
      },
    )
  })

  it('writes wire values under the documented param names, with no leading "?"', () => {
    const search = toShareSearch({
      questionType: 'compare',
      year: 2023,
      teamA: 'Georgia',
      teamB: 'Michigan',
      userTeam: 'Georgia',
      sport: 'cfb',
      method: 'elo',
    })

    expect(search.startsWith('?')).toBe(false)
    expect(Object.fromEntries(new URLSearchParams(search))).toEqual({
      q: 'compare',
      sport: 'cfb',
      year: '2023',
      engine: 'elo',
      a: 'Georgia',
      b: 'Michigan',
      for: 'Georgia',
    })
  })

  it('emits no "for" param when there is no user team', () => {
    const search = toShareSearch({
      questionType: 'champion',
      year: 2005,
      userTeam: null,
      sport: 'cfb',
      method: 'keener',
    })

    expect(new URLSearchParams(search).has('for')).toBe(false)
  })

  it('emits no team params a question type does not use', () => {
    const params = new URLSearchParams(
      toShareSearch({
        questionType: 'champion',
        year: 2005,
        userTeam: null,
        sport: 'cfb',
        method: 'keener',
      }),
    )

    expect(params.has('team')).toBe(false)
    expect(params.has('a')).toBe(false)
    expect(params.has('b')).toBe(false)
  })

  it('encodes and decodes "Texas A&M" and names with spaces', () => {
    const submission: QuestionSubmission = {
      questionType: 'compare',
      year: 2012,
      teamA: 'Texas A&M',
      teamB: 'Ole Miss',
      userTeam: 'Texas A&M',
      sport: 'cfb',
      method: 'keener',
    }

    const search = toShareSearch(submission)

    // The ampersand must not split the value into a new param.
    expect(search).not.toContain('Texas A&M')
    expect(new URLSearchParams(search).get('a')).toBe('Texas A&M')
    expect(fromShareSearch(search)).toEqual(submission)
  })

  it('accepts a leading "?", as `location.search` has one', () => {
    expect(fromShareSearch(`?${searchWith({})}`)).toEqual({
      questionType: 'compare',
      year: 2023,
      teamA: 'Georgia',
      teamB: 'Michigan',
      userTeam: 'Georgia',
      sport: 'cfb',
      method: 'elo',
    })
  })

  it('trims values, and reads a blank "for" as no user team', () => {
    expect(
      fromShareSearch(
        searchWith({ a: '  Georgia ', b: ' Michigan', for: '   ' }),
      ),
    ).toEqual({
      questionType: 'compare',
      year: 2023,
      teamA: 'Georgia',
      teamB: 'Michigan',
      userTeam: null,
      sport: 'cfb',
      method: 'elo',
    })
  })

  it('reads a missing "for" as no user team', () => {
    expect(fromShareSearch(searchWith({ for: null }))?.userTeam).toBeNull()
  })

  describe('returns null for anything malformed, all or nothing', () => {
    it.each([
      ['an empty search', ''],
      ['an unknown q', searchWith({ q: 'rankings' })],
      ['a missing q', searchWith({ q: null })],
      ['a bad sport', searchWith({ sport: 'mlb' })],
      ['a missing sport', searchWith({ sport: null })],
      ['a bad engine', searchWith({ engine: 'massey' })],
      [
        'a real API method the Engine toggle does not offer (elo_career)',
        searchWith({ engine: 'elo_career' }),
      ],
      [
        'a display label instead of the engine wire value',
        searchWith({ engine: 'Elo' }),
      ],
      ['a missing engine', searchWith({ engine: null })],
      ['a missing year', searchWith({ year: null })],
      ['a blank year', searchWith({ year: '' })],
      ['a non-integer year "2023.5"', searchWith({ year: '2023.5' })],
      ['a non-integer year "abc"', searchWith({ year: 'abc' })],
      ['an exponent year "2e3"', searchWith({ year: '2e3' })],
      ['compare missing a', searchWith({ a: null })],
      ['compare missing b', searchWith({ b: null })],
      ['compare with a blank b', searchWith({ b: '  ' })],
      [
        'team_case without team',
        new URLSearchParams({
          q: 'team_case',
          sport: 'cfb',
          year: '2010',
          engine: 'keener',
        }).toString(),
      ],
      [
        'team_case with a blank team',
        new URLSearchParams({
          q: 'team_case',
          sport: 'cfb',
          year: '2010',
          engine: 'keener',
          team: '   ',
        }).toString(),
      ],
    ])('%s', (_description, search) => {
      expect(fromShareSearch(search)).toBeNull()
    })
  })
})
