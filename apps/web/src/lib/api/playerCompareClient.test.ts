import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  PlayerApiError,
  SERVER_ERROR_COPY,
  VerdictHttpError,
  fetchPlayerComparison,
  searchPlayers,
} from './client'

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('player comparison and search client (issue #301)', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('asks for the comparison of a and b in the NFL', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, { a: {} }))
    vi.stubGlobal('fetch', fetchMock)

    await fetchPlayerComparison(2044124519, 2385180619)

    const [url] = fetchMock.mock.calls[0] as [string]
    const parsed = new URL(url)
    expect(parsed.pathname).toBe('/api/players/compare')
    expect(Object.fromEntries(parsed.searchParams)).toEqual({
      a: '2044124519',
      b: '2385180619',
      sport: 'nfl',
    })
  })

  it("rejects the comparison's typed 404 with a PlayerApiError", async () => {
    const detail = { error: 'unknown_player', player_id: 1, sport: 'nfl' }
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(jsonResponse(404, { detail })),
    )

    const error: unknown = await fetchPlayerComparison(2044124519, 1).catch(
      (caught: unknown) => caught,
    )

    expect(error).toBeInstanceOf(PlayerApiError)
    expect(error).toMatchObject({ status: 404, body: detail })
  })

  it('searches the NFL with the given text and limit', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, { rows: [] }))
    vi.stubGlobal('fetch', fetchMock)

    await searchPlayers('Mc Nair', 5)

    const [url] = fetchMock.mock.calls[0] as [string]
    const parsed = new URL(url)
    expect(parsed.pathname).toBe('/api/players/search')
    expect(Object.fromEntries(parsed.searchParams)).toEqual({
      q: 'Mc Nair',
      limit: '5',
      sport: 'nfl',
    })
  })

  it.each([
    ['fetchPlayerComparison', () => fetchPlayerComparison(1, 2)],
    ['searchPlayers', () => searchPlayers('mc')],
  ])('%s rejects a 500 with the 5xx copy', async (_name, send) => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(jsonResponse(500, { detail: 'boom' })),
    )

    const error: unknown = await send().catch((caught: unknown) => caught)

    expect(error).toBeInstanceOf(VerdictHttpError)
    expect((error as VerdictHttpError).message).toBe(SERVER_ERROR_COPY)
  })
})
