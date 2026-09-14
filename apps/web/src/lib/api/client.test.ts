import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  VerdictApiError,
  VerdictNetworkError,
  fetchChampion,
  fetchCompare,
  fetchCredits,
  fetchTeamCase,
  fetchTeams,
  fetchYears,
} from './client'

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('api client', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('resolves with the parsed envelope on a 200 response', async () => {
    const envelope = {
      evidence: {
        year: 2005,
        method: 'keener',
        team_id: 1,
        team_name: 'Texas',
        rank: 1,
        rating: 10,
        wins: 13,
        losses: 0,
        games: [],
        quality_wins: [],
        worst_loss: null,
      },
      narration: { text: 'Texas.', contested: false, cached: false },
    }
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, envelope))
    vi.stubGlobal('fetch', fetchMock)

    const result = await fetchChampion({
      year: 2005,
      user_team: null,
      sport: 'cfb',
      method: 'keener',
    })

    expect(result).toEqual(envelope)
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/api/verdict/champion'),
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({
          year: 2005,
          user_team: null,
          sport: 'cfb',
          method: 'keener',
        }),
      }),
    )
  })

  it.each([
    [
      'champion',
      () =>
        fetchChampion({
          year: 2005,
          user_team: null,
          sport: 'cfb',
          method: 'elo',
        }),
    ],
    [
      'team-case',
      () =>
        fetchTeamCase({
          year: 2005,
          team: 'USC',
          user_team: null,
          sport: 'cfb',
          method: 'elo',
        }),
    ],
    [
      'compare',
      () =>
        fetchCompare({
          year: 2005,
          team_a: 'Texas',
          team_b: 'USC',
          user_team: null,
          sport: 'cfb',
          method: 'elo',
        }),
    ],
  ])(
    'sends the selected method in the %s request body (issue #154)',
    async (route, send) => {
      const fetchMock = vi
        .fn()
        .mockResolvedValue(jsonResponse(200, { evidence: {}, narration: {} }))
      vi.stubGlobal('fetch', fetchMock)

      await send()

      const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]
      expect(url).toContain(`/api/verdict/${route}`)
      expect(JSON.parse(String(init.body))).toMatchObject({ method: 'elo' })
    },
  )

  it('throws a VerdictApiError with the parsed error body on a mapped 4xx response', async () => {
    const detail = {
      error: 'unknown_year',
      year: 1899,
      available_years: [2004, 2005],
    }
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockImplementation(() =>
          Promise.resolve(jsonResponse(404, { detail })),
        ),
    )

    await expect(
      fetchChampion({
        year: 1899,
        user_team: null,
        sport: 'cfb',
        method: 'keener',
      }),
    ).rejects.toMatchObject({
      status: 404,
      body: detail,
    })
    await expect(
      fetchChampion({
        year: 1899,
        user_team: null,
        sport: 'cfb',
        method: 'keener',
      }),
    ).rejects.toBeInstanceOf(VerdictApiError)
  })

  it('throws a VerdictNetworkError when fetch itself rejects', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockRejectedValue(new TypeError('Failed to fetch')),
    )

    await expect(
      fetchCompare({
        year: 2005,
        team_a: 'Texas',
        team_b: 'USC',
        user_team: null,
        sport: 'cfb',
        method: 'keener',
      }),
    ).rejects.toBeInstanceOf(VerdictNetworkError)
  })

  it('throws a VerdictNetworkError on an unmapped error response shape', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(jsonResponse(500, { detail: 'boom' })),
    )

    await expect(
      fetchChampion({
        year: 2005,
        user_team: null,
        sport: 'cfb',
        method: 'keener',
      }),
    ).rejects.toBeInstanceOf(VerdictNetworkError)
  })
})

describe('fetchCredits', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('resolves with the parsed credits payload on a 200 response', async () => {
    const credits = {
      methodologies: [
        {
          name: "Keener's method",
          citation:
            'Keener, J. P. (1993). The Perron-Frobenius theorem and the ranking of football teams.',
          url: 'https://example.com/keener',
          summary: 'Eigenvector-based strength-of-schedule ranking.',
        },
        {
          name: 'Elo',
          citation: 'Arpad E. Elo, The Rating of Chessplayers (1978).',
          url: 'https://example.com/elo',
          summary: 'Teams trade rating points after every game.',
        },
      ],
      data_sources: [
        {
          name: 'CollegeFootballData.com',
          url: 'https://collegefootballdata.com',
          note: 'Game results and team data.',
        },
        {
          name: 'nflverse (Lee Sharpe)',
          url: 'https://github.com/nflverse/nflverse-data',
          note: 'NFL play-by-play and schedule data.',
        },
      ],
    }
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, credits))
    vi.stubGlobal('fetch', fetchMock)

    const result = await fetchCredits()

    expect(result).toEqual(credits)
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/api/credits'),
    )
  })

  it('throws a VerdictNetworkError when fetch itself rejects', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockRejectedValue(new TypeError('Failed to fetch')),
    )

    await expect(fetchCredits()).rejects.toBeInstanceOf(VerdictNetworkError)
  })

  it('throws a VerdictNetworkError on a non-2xx response', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(jsonResponse(500, { detail: 'boom' })),
    )

    await expect(fetchCredits()).rejects.toBeInstanceOf(VerdictNetworkError)
  })
})

describe('fetchYears', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('resolves with the parsed years list on a 200 response, defaulting to sport=cfb and method=keener', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse(200, { years: [2004, 2005, 2006] }))
    vi.stubGlobal('fetch', fetchMock)

    const result = await fetchYears()

    expect(result).toEqual({ years: [2004, 2005, 2006] })
    const [url] = fetchMock.mock.calls[0] as [string]
    expect(url).toContain('/api/years')
    expect(url).toContain('sport=cfb')
    expect(url).toContain('method=keener')
  })

  it('passes an explicit sport through as a query param', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse(200, { years: [2021, 2022] }))
    vi.stubGlobal('fetch', fetchMock)

    await fetchYears('nfl')

    const [url] = fetchMock.mock.calls[0] as [string]
    expect(url).toContain('sport=nfl')
  })

  it('passes an explicit method through as a query param (issue #154)', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse(200, { years: [2005] }))
    vi.stubGlobal('fetch', fetchMock)

    await fetchYears('nfl', 'elo')

    const [url] = fetchMock.mock.calls[0] as [string]
    const params = new URL(url).searchParams
    expect(params.get('sport')).toBe('nfl')
    expect(params.get('method')).toBe('elo')
  })

  it('sends exactly `?sport=...&method=...` and nothing else', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse(200, { years: [2004, 2005] }))
    vi.stubGlobal('fetch', fetchMock)

    await fetchYears('cfb', 'elo')

    const [url] = fetchMock.mock.calls[0] as [string]
    expect(new URL(url).search).toBe('?sport=cfb&method=elo')
  })

  it('throws a VerdictNetworkError when fetch itself rejects', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockRejectedValue(new TypeError('Failed to fetch')),
    )

    await expect(fetchYears()).rejects.toBeInstanceOf(VerdictNetworkError)
  })

  it('throws a VerdictNetworkError on a non-2xx response', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(jsonResponse(500, { detail: 'boom' })),
    )

    await expect(fetchYears()).rejects.toBeInstanceOf(VerdictNetworkError)
  })
})

describe('fetchTeams', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('resolves with the parsed team list on a 200 response, defaulting to sport=cfb and method=keener', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse(200, {
        teams: ['Texas', 'USC'],
        team_details: [
          { name: 'Texas', mascot: 'Longhorns', aliases: ['TEX'] },
          { name: 'USC', mascot: 'Trojans', aliases: [] },
        ],
      }),
    )
    vi.stubGlobal('fetch', fetchMock)

    const result = await fetchTeams()

    expect(result.teams).toEqual(['Texas', 'USC'])
    expect(result.team_details).toEqual([
      { name: 'Texas', mascot: 'Longhorns', aliases: ['TEX'] },
      { name: 'USC', mascot: 'Trojans', aliases: [] },
    ])
    const [url] = fetchMock.mock.calls[0] as [string]
    expect(url).toContain('/api/teams')
    expect(url).toContain('sport=cfb')
    expect(url).toContain('method=keener')
  })

  it('sends the year as a query param when one is given', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse(200, { teams: [], team_details: [] }))
    vi.stubGlobal('fetch', fetchMock)

    await fetchTeams('cfb', 'keener', 2005)

    const [url] = fetchMock.mock.calls[0] as [string]
    expect(url).toContain('sport=cfb')
    expect(url).toContain('year=2005')
  })

  it('passes an explicit method through as a query param, alongside sport and year (issue #154)', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse(200, { teams: [], team_details: [] }))
    vi.stubGlobal('fetch', fetchMock)

    await fetchTeams('cfb', 'elo', 2005)

    const [url] = fetchMock.mock.calls[0] as [string]
    expect(new URL(url).search).toBe('?sport=cfb&method=elo&year=2005')
  })

  it.each([
    ['omitted', undefined],
    ['NaN', Number.NaN],
    ['Infinity', Number.POSITIVE_INFINITY],
    // Finite, but not a season -- and `apps/api` declares `year: int`, so
    // sending it would be a 422 rather than the full per-sport list (#101).
    ['a non-integer (2018.5)', 2018.5],
  ])('sends no year param at all when the year is %s', async (_label, year) => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse(200, { teams: [], team_details: [] }))
    vi.stubGlobal('fetch', fetchMock)

    await fetchTeams('cfb', 'elo', year)

    const [url] = fetchMock.mock.calls[0] as [string]
    expect(url).not.toContain('year')
    expect(url).toContain('sport=cfb')
    // Dropping the year never drops the method.
    expect(url).toContain('method=elo')
  })

  it('passes an explicit sport through as a query param', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        jsonResponse(200, { teams: ['Chiefs', 'Bills'], team_details: [] }),
      )
    vi.stubGlobal('fetch', fetchMock)

    await fetchTeams('nfl')

    const [url] = fetchMock.mock.calls[0] as [string]
    expect(url).toContain('sport=nfl')
  })

  it('throws a VerdictNetworkError when fetch itself rejects', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockRejectedValue(new TypeError('Failed to fetch')),
    )

    await expect(fetchTeams()).rejects.toBeInstanceOf(VerdictNetworkError)
  })

  it('throws a VerdictNetworkError on a non-2xx response', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(jsonResponse(500, { detail: 'boom' })),
    )

    await expect(fetchTeams()).rejects.toBeInstanceOf(VerdictNetworkError)
  })
})
