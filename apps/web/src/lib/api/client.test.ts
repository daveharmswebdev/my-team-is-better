import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  VerdictApiError,
  VerdictNetworkError,
  fetchChampion,
  fetchCompare,
  fetchCredits,
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
    })

    expect(result).toEqual(envelope)
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/api/verdict/champion'),
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ year: 2005, user_team: null, sport: 'cfb' }),
      }),
    )
  })

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
      fetchChampion({ year: 1899, user_team: null, sport: 'cfb' }),
    ).rejects.toMatchObject({
      status: 404,
      body: detail,
    })
    await expect(
      fetchChampion({ year: 1899, user_team: null, sport: 'cfb' }),
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
      }),
    ).rejects.toBeInstanceOf(VerdictNetworkError)
  })

  it('throws a VerdictNetworkError on an unmapped error response shape', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(jsonResponse(500, { detail: 'boom' })),
    )

    await expect(
      fetchChampion({ year: 2005, user_team: null, sport: 'cfb' }),
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

  it('resolves with the parsed years list on a 200 response, defaulting to sport=cfb', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse(200, { years: [2004, 2005, 2006] }))
    vi.stubGlobal('fetch', fetchMock)

    const result = await fetchYears()

    expect(result).toEqual({ years: [2004, 2005, 2006] })
    const [url] = fetchMock.mock.calls[0] as [string]
    expect(url).toContain('/api/years')
    expect(url).toContain('sport=cfb')
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

  it('sends exactly `?sport=...` and nothing else', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse(200, { years: [2004, 2005] }))
    vi.stubGlobal('fetch', fetchMock)

    await fetchYears('cfb')

    const [url] = fetchMock.mock.calls[0] as [string]
    expect(new URL(url).search).toBe('?sport=cfb')
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

  it('resolves with the parsed team list on a 200 response, defaulting to sport=cfb', async () => {
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
  })

  it('sends the year as a query param when one is given', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse(200, { teams: [], team_details: [] }))
    vi.stubGlobal('fetch', fetchMock)

    await fetchTeams('cfb', 2005)

    const [url] = fetchMock.mock.calls[0] as [string]
    expect(url).toContain('sport=cfb')
    expect(url).toContain('year=2005')
  })

  it.each([
    ['omitted', undefined],
    ['NaN', Number.NaN],
    ['Infinity', Number.POSITIVE_INFINITY],
  ])('sends no year param at all when the year is %s', async (_label, year) => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse(200, { teams: [], team_details: [] }))
    vi.stubGlobal('fetch', fetchMock)

    await fetchTeams('cfb', year)

    const [url] = fetchMock.mock.calls[0] as [string]
    expect(url).not.toContain('year')
    expect(url).toContain('sport=cfb')
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
