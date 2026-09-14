import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  CATALOG_TIMEOUT_MS,
  CLIENT_ERROR_COPY,
  NETWORK_ERROR_COPY,
  SERVER_ERROR_COPY,
  VERDICT_TIMEOUT_MS,
  VerdictApiError,
  VerdictHttpError,
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

const CHAMPION_2005 = {
  year: 2005,
  user_team: null,
  sport: 'cfb',
  method: 'keener',
} as const

/**
 * A `fetch` that never answers on its own, and rejects with an `AbortError`
 * the moment its request's signal aborts -- as a real browser `fetch` does.
 * Hands back the signal each call was given, so a test can inspect it.
 */
function neverAnsweringFetch() {
  const signals: (AbortSignal | undefined)[] = []
  const fetchMock = vi.fn(
    (_url: string, init?: RequestInit) =>
      new Promise<Response>((_resolve, reject) => {
        const signal = init?.signal ?? undefined
        signals.push(signal)
        signal?.addEventListener('abort', () => {
          reject(new DOMException('The operation was aborted.', 'AbortError'))
        })
      }),
  )
  return { fetchMock, signals }
}

/**
 * Tracks whether `promise` has settled, without a rejection going unhandled.
 * Read `state.settled` only after `flushMicrotasks()`.
 */
function track(promise: Promise<unknown>) {
  const state: { settled: boolean; error: unknown } = {
    settled: false,
    error: undefined,
  }
  promise.then(
    () => {
      state.settled = true
    },
    (error: unknown) => {
      state.settled = true
      state.error = error
    },
  )
  return state
}

/** Lets a chain of already-queued promise reactions run to the end. */
async function flushMicrotasks() {
  for (let i = 0; i < 20; i += 1) {
    await Promise.resolve()
  }
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

  it('throws a VerdictNetworkError with the network copy when fetch itself rejects', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockRejectedValue(new TypeError('Failed to fetch')),
    )

    const rejection = fetchCompare({
      year: 2005,
      team_a: 'Texas',
      team_b: 'USC',
      user_team: null,
      sport: 'cfb',
      method: 'keener',
    })

    await expect(rejection).rejects.toBeInstanceOf(VerdictNetworkError)
    await expect(rejection).rejects.toThrow(NETWORK_ERROR_COPY)
  })

  /**
   * The system-error copy is the narrator's voice (coordinator amendment to
   * #214/#215), pinned here once so every other test can assert against the
   * constants.
   */
  it('keeps the system-error copy verbatim', () => {
    expect(NETWORK_ERROR_COPY).toBe(
      "Lost you there, pal. Couldn't get through. Check your connection and ask me again.",
    )
    expect(CLIENT_ERROR_COPY).toBe(
      "Didn't catch that one, pal. Something in the question came through garbled. Check it and ask me again.",
    )
    expect(SERVER_ERROR_COPY).toBe(
      "Hang on, something broke in the back. That's on us, not you. Give it a minute and ask me again.",
    )
  })

  it('throws a VerdictHttpError, not a VerdictNetworkError, on an unmapped error response shape', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(jsonResponse(500, { detail: 'boom' })),
    )

    const rejection = fetchChampion(CHAMPION_2005)

    await expect(rejection).rejects.toBeInstanceOf(VerdictHttpError)
    await expect(rejection).rejects.not.toBeInstanceOf(VerdictNetworkError)
  })
})

/**
 * Issue #215: a non-OK response that isn't the API's typed error body is
 * shown to the user as plain copy by status class. The status and the raw
 * body stay on the error object and in the console, never in the message.
 */
describe('unmapped HTTP errors (issue #215)', () => {
  beforeEach(() => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  async function rejectionOf(promise: Promise<unknown>): Promise<unknown> {
    try {
      await promise
    } catch (error) {
      return error
    }
    throw new Error('expected the request to reject')
  }

  it('maps a FastAPI request-validation 422 to the 4xx copy, with no status in the message', async () => {
    const body = {
      detail: [
        {
          loc: ['body', 'year'],
          msg: 'Input should be a valid integer',
          type: 'int_parsing',
        },
      ],
    }
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(422, body)))

    const error = await rejectionOf(fetchChampion(CHAMPION_2005))

    expect(error).toBeInstanceOf(VerdictHttpError)
    const httpError = error as VerdictHttpError
    expect(httpError.status).toBe(422)
    expect(httpError.message).toBe(CLIENT_ERROR_COPY)
    expect(httpError.message).not.toMatch(/status/i)
    expect(httpError.message).not.toMatch(/422/)
    expect(httpError.bodyText).toBe(JSON.stringify(body))
  })

  it('maps an empty 500 to the 5xx copy, with no status in the message', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(new Response(null, { status: 500 })),
    )

    const error = await rejectionOf(fetchChampion(CHAMPION_2005))

    expect(error).toBeInstanceOf(VerdictHttpError)
    const httpError = error as VerdictHttpError
    expect(httpError.status).toBe(500)
    expect(httpError.message).toBe(SERVER_ERROR_COPY)
    expect(httpError.message).not.toMatch(/status/i)
    expect(httpError.message).not.toMatch(/500/)
    expect(httpError.bodyText).toBe('')
  })

  it("maps a proxy's HTML 503 to the 5xx copy, keeping the raw HTML on bodyText and logging it", async () => {
    const html = '<html>Service Unavailable</html>'
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(html, {
          status: 503,
          headers: { 'Content-Type': 'text/html' },
        }),
      ),
    )

    const error = await rejectionOf(fetchChampion(CHAMPION_2005))

    expect(error).toBeInstanceOf(VerdictHttpError)
    const httpError = error as VerdictHttpError
    expect(httpError.status).toBe(503)
    expect(httpError.message).toBe(SERVER_ERROR_COPY)
    expect(httpError.bodyText).toBe(html)
    // Developers still see both, once, in dev tools.
    expect(console.error).toHaveBeenCalledTimes(1)
    const logged = JSON.stringify(vi.mocked(console.error).mock.calls[0])
    expect(logged).toContain('503')
    expect(logged).toContain('Service Unavailable')
  })

  it('still throws a VerdictApiError for a typed 404 unknown_year (regression guard)', async () => {
    const detail = {
      error: 'unknown_year',
      year: 1899,
      available_years: [2004, 2005],
    }
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(jsonResponse(404, { detail })),
    )

    const error = await rejectionOf(fetchChampion(CHAMPION_2005))

    expect(error).toBeInstanceOf(VerdictApiError)
    expect(error).not.toBeInstanceOf(VerdictHttpError)
    expect(error).toMatchObject({ status: 404, body: detail })
  })

  it.each([
    ['fetchCredits', () => fetchCredits()],
    ['fetchYears', () => fetchYears()],
    ['fetchTeams', () => fetchTeams()],
  ])(
    '%s rejects a 500 with a VerdictHttpError and the 5xx copy',
    async (_name, send) => {
      vi.stubGlobal(
        'fetch',
        vi.fn().mockResolvedValue(jsonResponse(500, { detail: 'boom' })),
      )

      const error = await rejectionOf(send())

      expect(error).toBeInstanceOf(VerdictHttpError)
      expect((error as VerdictHttpError).status).toBe(500)
      expect((error as VerdictHttpError).message).toBe(SERVER_ERROR_COPY)
      expect((error as VerdictHttpError).message).not.toMatch(/status|500/i)
    },
  )
})

/**
 * Issue #214: a verdict request that never settles times out as a network
 * error, and a caller can abort one it no longer wants.
 */
describe('verdict request timeout and abort (issue #214)', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('is still pending one millisecond before VERDICT_TIMEOUT_MS, and rejects with the network copy at it', async () => {
    const { fetchMock, signals } = neverAnsweringFetch()
    vi.stubGlobal('fetch', fetchMock)

    const request = fetchChampion(CHAMPION_2005)
    const outcome = track(request)

    await vi.advanceTimersByTimeAsync(VERDICT_TIMEOUT_MS - 1)
    await flushMicrotasks()
    expect(outcome.settled).toBe(false)
    expect(signals[0]?.aborted).toBe(false)

    await vi.advanceTimersByTimeAsync(1)
    await flushMicrotasks()
    // Settles only because the request's own signal aborted, and the fetch
    // gave up on it -- a fetch that ignored its signal would still be pending.
    expect(outcome.settled).toBe(true)
    expect(signals[0]?.aborted).toBe(true)
    expect(outcome.error).toBeInstanceOf(VerdictNetworkError)
    expect((outcome.error as VerdictNetworkError).message).toBe(
      NETWORK_ERROR_COPY,
    )
    expect(vi.getTimerCount()).toBe(0)
  })

  it('also times out when the headers arrive but the body never finishes', async () => {
    const response = jsonResponse(200, {})
    vi.spyOn(response, 'json').mockReturnValue(new Promise(() => {}))
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response))

    const request = fetchChampion(CHAMPION_2005)
    const outcome = track(request)

    await vi.advanceTimersByTimeAsync(VERDICT_TIMEOUT_MS - 1)
    await flushMicrotasks()
    expect(outcome.settled).toBe(false)

    await vi.advanceTimersByTimeAsync(1)
    await flushMicrotasks()
    expect(outcome.settled).toBe(true)
    expect(outcome.error).toBeInstanceOf(VerdictNetworkError)
    expect((outcome.error as VerdictNetworkError).message).toBe(
      NETWORK_ERROR_COPY,
    )
  })

  it.each([
    [
      'fetchChampion',
      (signal: AbortSignal) => fetchChampion(CHAMPION_2005, { signal }),
    ],
    [
      'fetchTeamCase',
      (signal: AbortSignal) =>
        fetchTeamCase({ ...CHAMPION_2005, team: 'Texas' }, { signal }),
    ],
    [
      'fetchCompare',
      (signal: AbortSignal) =>
        fetchCompare(
          { ...CHAMPION_2005, team_a: 'Texas', team_b: 'USC' },
          { signal },
        ),
    ],
  ])(
    "%s rejects with an AbortError when the caller's signal aborts, leaving no timer behind",
    async (_name, send) => {
      const { fetchMock } = neverAnsweringFetch()
      vi.stubGlobal('fetch', fetchMock)
      const controller = new AbortController()

      const request = send(controller.signal)
      const outcome = track(request)
      await flushMicrotasks()
      expect(outcome.settled).toBe(false)

      controller.abort()
      await flushMicrotasks()

      expect(outcome.settled).toBe(true)
      expect(outcome.error).toBeInstanceOf(DOMException)
      expect((outcome.error as DOMException).name).toBe('AbortError')
      expect(outcome.error).not.toBeInstanceOf(VerdictNetworkError)
      expect(outcome.error).not.toBeInstanceOf(VerdictHttpError)
      expect(vi.getTimerCount()).toBe(0)
    },
  )

  it('clears its timer once a successful response has been read', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(200, {})))

    await fetchChampion(CHAMPION_2005)

    expect(vi.getTimerCount()).toBe(0)
  })
})

/**
 * Issue #237: the catalog and credits GETs are bounded too, so a hung
 * `/api/credits`, `/api/years` or `/api/teams` fails like a dropped
 * connection instead of leaving the UI pending forever.
 */
describe('GET request timeout (issue #237)', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  const GETS = [
    ['fetchCredits', () => fetchCredits()],
    ['fetchYears', () => fetchYears('nfl', 'elo')],
    ['fetchTeams', () => fetchTeams('cfb', 'keener', 2005)],
  ] as const

  it('is shorter than the verdict timeout', () => {
    expect(CATALOG_TIMEOUT_MS).toBeGreaterThan(0)
    expect(CATALOG_TIMEOUT_MS).toBeLessThan(VERDICT_TIMEOUT_MS)
  })

  it.each(GETS)(
    '%s is still pending one millisecond before CATALOG_TIMEOUT_MS, and rejects with the network copy at it',
    async (_name, send) => {
      const { fetchMock, signals } = neverAnsweringFetch()
      vi.stubGlobal('fetch', fetchMock)

      const outcome = track(send())

      await vi.advanceTimersByTimeAsync(CATALOG_TIMEOUT_MS - 1)
      await flushMicrotasks()
      expect(outcome.settled).toBe(false)
      expect(signals).toHaveLength(1)
      expect(signals[0]).toBeInstanceOf(AbortSignal)
      expect(signals[0]?.aborted).toBe(false)

      await vi.advanceTimersByTimeAsync(1)
      await flushMicrotasks()
      // Settles only because the request's own signal aborted.
      expect(outcome.settled).toBe(true)
      expect(signals[0]?.aborted).toBe(true)
      expect(outcome.error).toBeInstanceOf(VerdictNetworkError)
      expect((outcome.error as VerdictNetworkError).message).toBe(
        NETWORK_ERROR_COPY,
      )
      expect(vi.getTimerCount()).toBe(0)
    },
  )

  it.each(GETS)(
    '%s also times out when the headers arrive but the JSON body never finishes',
    async (_name, send) => {
      const response = jsonResponse(200, {})
      vi.spyOn(response, 'json').mockReturnValue(new Promise(() => {}))
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response))

      const outcome = track(send())

      await vi.advanceTimersByTimeAsync(CATALOG_TIMEOUT_MS - 1)
      await flushMicrotasks()
      expect(outcome.settled).toBe(false)

      await vi.advanceTimersByTimeAsync(1)
      await flushMicrotasks()
      expect(outcome.settled).toBe(true)
      expect(outcome.error).toBeInstanceOf(VerdictNetworkError)
      expect((outcome.error as VerdictNetworkError).message).toBe(
        NETWORK_ERROR_COPY,
      )
      expect(vi.getTimerCount()).toBe(0)
    },
  )

  it.each(GETS)(
    '%s clears its timer once a successful response has been read',
    async (_name, send) => {
      vi.stubGlobal(
        'fetch',
        vi
          .fn()
          .mockResolvedValue(
            jsonResponse(200, { years: [], teams: [], team_details: [] }),
          ),
      )

      await send()

      expect(vi.getTimerCount()).toBe(0)
    },
  )

  it.each(GETS)(
    '%s clears its timer after an HTTP error, which stays a VerdictHttpError',
    async (_name, send) => {
      vi.spyOn(console, 'error').mockImplementation(() => {})
      vi.stubGlobal(
        'fetch',
        vi.fn().mockResolvedValue(jsonResponse(503, { detail: 'boom' })),
      )

      const outcome = track(send())
      await flushMicrotasks()

      expect(outcome.settled).toBe(true)
      expect(outcome.error).toBeInstanceOf(VerdictHttpError)
      expect(vi.getTimerCount()).toBe(0)
    },
  )
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
    // Issue #237: every GET carries the signal its timeout aborts.
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/api/credits'),
      expect.objectContaining({ signal: expect.any(AbortSignal) as unknown }),
    )
  })

  it('throws a VerdictNetworkError when fetch itself rejects', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockRejectedValue(new TypeError('Failed to fetch')),
    )

    await expect(fetchCredits()).rejects.toBeInstanceOf(VerdictNetworkError)
    await expect(fetchCredits()).rejects.toThrow(NETWORK_ERROR_COPY)
  })

  it('throws a VerdictHttpError on a non-2xx response', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(jsonResponse(500, { detail: 'boom' })),
    )

    await expect(fetchCredits()).rejects.toBeInstanceOf(VerdictHttpError)
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
    await expect(fetchYears()).rejects.toThrow(NETWORK_ERROR_COPY)
  })

  it('throws a VerdictHttpError on a non-2xx response', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(jsonResponse(500, { detail: 'boom' })),
    )

    await expect(fetchYears()).rejects.toBeInstanceOf(VerdictHttpError)
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
    await expect(fetchTeams()).rejects.toThrow(NETWORK_ERROR_COPY)
  })

  it('throws a VerdictHttpError on a non-2xx response', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(jsonResponse(500, { detail: 'boom' })),
    )

    await expect(fetchTeams()).rejects.toBeInstanceOf(VerdictHttpError)
  })
})
