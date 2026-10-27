import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  BRADY_ID,
  BRADY_VS_MANNING_VERDICT,
  PEYTON_MANNING_ID,
} from '../qbScoreFixtures'
import {
  CLIENT_ERROR_COPY,
  NETWORK_ERROR_COPY,
  PlayerApiError,
  PlayersNotComparableError,
  SERVER_ERROR_COPY,
  VERDICT_TIMEOUT_MS,
  VerdictHttpError,
  VerdictNetworkError,
  fetchQbVerdict,
} from './client'
import { hang, networkError } from '../../mocks/handlers'
import { answerEveryRequest } from '../../test/network'

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

/** The rejection of `request`, which must reject. */
async function rejection(request: Promise<unknown>): Promise<unknown> {
  return request.then(
    () => {
      throw new Error('expected the request to reject')
    },
    (error: unknown) => error,
  )
}

describe('fetchQbVerdict: POST /api/players/compare/verdict (issue #459)', () => {
  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  it('posts both ids and the NFL as JSON, and resolves with the envelope', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse(200, BRADY_VS_MANNING_VERDICT))
    answerEveryRequest(fetchMock)

    const envelope = await fetchQbVerdict(BRADY_ID, PEYTON_MANNING_ID)

    expect(envelope).toEqual(BRADY_VS_MANNING_VERDICT)
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(new URL(url).pathname).toBe('/api/players/compare/verdict')
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body as string)).toEqual({
      a: BRADY_ID,
      b: PEYTON_MANNING_ID,
      sport: 'nfl',
    })
  })

  // Bodies verbatim from production (2026-10-25).
  it('rejects the 400 players_not_comparable with a PlayersNotComparableError', async () => {
    const detail = {
      error: 'players_not_comparable',
      a_group: 'QB',
      b_group: 'RB',
    }
    answerEveryRequest(vi.fn().mockResolvedValue(jsonResponse(400, { detail })))

    const error = await rejection(fetchQbVerdict(BRADY_ID, 1))

    expect(error).toBeInstanceOf(PlayersNotComparableError)
    expect(error).toMatchObject({ status: 400, body: detail })
  })

  it('rejects the 404 unknown_player with a PlayerApiError', async () => {
    const detail = { error: 'unknown_player', player_id: 1, sport: 'nfl' }
    answerEveryRequest(vi.fn().mockResolvedValue(jsonResponse(404, { detail })))

    const error = await rejection(fetchQbVerdict(BRADY_ID, 1))

    expect(error).toBeInstanceOf(PlayerApiError)
    expect(error).toMatchObject({ status: 404, body: detail })
  })

  it('rejects a request-validation 422 with a VerdictHttpError carrying the client copy', async () => {
    const detail = [
      {
        type: 'value_error',
        loc: ['body', 'b'],
        msg: 'Value error, b must be a different player from a',
        input: BRADY_ID,
      },
    ]
    vi.spyOn(console, 'error').mockImplementation(() => {})
    answerEveryRequest(vi.fn().mockResolvedValue(jsonResponse(422, { detail })))

    const error = await rejection(fetchQbVerdict(BRADY_ID, BRADY_ID))

    expect(error).toBeInstanceOf(VerdictHttpError)
    expect(error).toMatchObject({ status: 422, message: CLIENT_ERROR_COPY })
  })

  it('rejects the stale-db 503 with a VerdictHttpError carrying the server copy', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    answerEveryRequest(vi
        .fn()
        .mockResolvedValue(
          jsonResponse(503, { detail: { error: 'stale_database' } }),
        ))

    const error = await rejection(fetchQbVerdict(BRADY_ID, PEYTON_MANNING_ID))

    expect(error).toBeInstanceOf(VerdictHttpError)
    expect(error).toMatchObject({ status: 503, message: SERVER_ERROR_COPY })
  })

  it('rejects an unreachable API with a VerdictNetworkError', async () => {
    answerEveryRequest(vi.fn().mockResolvedValue(networkError()))

    const error = await rejection(fetchQbVerdict(BRADY_ID, PEYTON_MANNING_ID))

    expect(error).toBeInstanceOf(VerdictNetworkError)
    expect((error as Error).message).toBe(NETWORK_ERROR_COPY)
  })

  it('times out at VERDICT_TIMEOUT_MS with a VerdictNetworkError', async () => {
    vi.useFakeTimers()
    // Hangs; the client's fetch rejects once the request's signal aborts.
    answerEveryRequest(hang)

    const settled = rejection(fetchQbVerdict(BRADY_ID, PEYTON_MANNING_ID))
    await vi.advanceTimersByTimeAsync(VERDICT_TIMEOUT_MS)
    const error = await settled

    expect(error).toBeInstanceOf(VerdictNetworkError)
    expect((error as Error).message).toBe(NETWORK_ERROR_COPY)
  })

  it("rejects with an AbortError when the caller's signal aborts", async () => {
    // Hangs; the client's fetch rejects once the request's signal aborts.
    answerEveryRequest(hang)
    const controller = new AbortController()

    const settled = rejection(
      fetchQbVerdict(BRADY_ID, PEYTON_MANNING_ID, {
        signal: controller.signal,
      }),
    )
    controller.abort()
    const error = await settled

    expect(error).toBeInstanceOf(DOMException)
    expect((error as DOMException).name).toBe('AbortError')
  })
})
