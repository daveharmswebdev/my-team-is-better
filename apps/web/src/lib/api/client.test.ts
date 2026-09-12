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

    const result = await fetchChampion({ year: 2005, user_team: null })

    expect(result).toEqual(envelope)
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/api/verdict/champion'),
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ year: 2005, user_team: null }),
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
      fetchChampion({ year: 1899, user_team: null }),
    ).rejects.toMatchObject({
      status: 404,
      body: detail,
    })
    await expect(
      fetchChampion({ year: 1899, user_team: null }),
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
      }),
    ).rejects.toBeInstanceOf(VerdictNetworkError)
  })

  it('throws a VerdictNetworkError on an unmapped error response shape', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(jsonResponse(500, { detail: 'boom' })),
    )

    await expect(
      fetchChampion({ year: 2005, user_team: null }),
    ).rejects.toBeInstanceOf(VerdictNetworkError)
  })
})

describe('fetchCredits', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('resolves with the parsed credits payload on a 200 response', async () => {
    const credits = {
      methodology: {
        name: 'Keener',
        citation:
          'Keener, J. P. (1993). The Perron-Frobenius theorem and the ranking of football teams.',
        url: 'https://example.com/keener',
        summary: 'Eigenvector-based strength-of-schedule ranking.',
      },
      data_source: {
        name: 'CollegeFootballData.com',
        url: 'https://collegefootballdata.com',
        note: 'Game results and team data.',
      },
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

  it('resolves with the parsed years list on a 200 response, with no sport param', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse(200, { years: [2004, 2005, 2006] }))
    vi.stubGlobal('fetch', fetchMock)

    const result = await fetchYears()

    expect(result).toEqual({ years: [2004, 2005, 2006] })
    const [url] = fetchMock.mock.calls[0] as [string]
    expect(url).toContain('/api/years')
    expect(url).not.toContain('sport')
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

  it('resolves with the parsed team list on a 200 response, with no sport param', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse(200, { teams: ['Texas', 'USC'] }))
    vi.stubGlobal('fetch', fetchMock)

    const result = await fetchTeams()

    expect(result).toEqual({ teams: ['Texas', 'USC'] })
    const [url] = fetchMock.mock.calls[0] as [string]
    expect(url).toContain('/api/teams')
    expect(url).not.toContain('sport')
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
