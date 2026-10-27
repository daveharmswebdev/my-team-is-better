import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { PlayerPositionGroup, PlayerSearchOut } from '../../lib/api/types'
import { SEARCH_MC, SEARCH_MCNAIR } from '../../lib/playerFixtures'
import { SEARCH_DEBOUNCE_MS, usePlayerSearch } from './usePlayerSearch'

import { playerSearchHandler } from '../../mocks/handlers'
import { server } from '../../test/server'

/** `GET /api/players/search`, answered through MSW (issue #221). */
const mockedSearch = vi.fn<Parameters<typeof playerSearchHandler>[0]>()

interface Sent {
  query: string
  signal: AbortSignal
  resolve: (answer: PlayerSearchOut) => void
}

/**
 * Every search hangs until the test settles it. A caller abort rejects it in
 * the real client, which hands the request's signal to `fetch`.
 */
function recordSearches(): Sent[] {
  const sent: Sent[] = []
  mockedSearch.mockImplementation((query, options) => {
    const signal = options.signal
    return new Promise<PlayerSearchOut>((resolve) => {
      sent.push({ query, signal, resolve })
    })
  })
  return sent
}

/** Lets the debounce fire, then flushes the promise callbacks it set off. */
async function passDebounce() {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(SEARCH_DEBOUNCE_MS)
  })
}

describe('usePlayerSearch: a superseded search is aborted (issue #370)', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    mockedSearch.mockReset()
    server.use(playerSearchHandler(mockedSearch))
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it("aborts the first request's signal when the text changes before it answers (b)", async () => {
    const sent = recordSearches()
    const { rerender } = renderHook(({ text }) => usePlayerSearch(text), {
      initialProps: { text: 'mc' },
    })
    await passDebounce()
    expect(sent).toHaveLength(1)
    expect(sent[0]?.signal?.aborted).toBe(false)

    rerender({ text: 'McNair' })

    expect(sent[0]?.signal?.aborted).toBe(true)
  })

  it('a burst of typing has at most one search in flight', async () => {
    const sent = recordSearches()
    const { rerender } = renderHook(({ text }) => usePlayerSearch(text), {
      initialProps: { text: 'mc' },
    })
    for (const text of ['mcn', 'mcna', 'mcnai', 'McNair']) {
      await passDebounce()
      rerender({ text })
    }
    await passDebounce()

    expect(sent.map((s) => s.query)).toEqual([
      'mc',
      'mcn',
      'mcna',
      'mcnai',
      'McNair',
    ])
    const inFlight = sent.filter((s) => s.signal?.aborted !== true)
    expect(inFlight.map((s) => s.query)).toEqual(['McNair'])
  })

  it("the aborted request's rejection never shows an error for the new query (c)", async () => {
    const sent = recordSearches()
    const { result, rerender } = renderHook(
      ({ text }) => usePlayerSearch(text),
      { initialProps: { text: 'mc' } },
    )
    await passDebounce()
    await act(async () => {
      sent[0]?.resolve(SEARCH_MC)
      await Promise.resolve()
    })
    expect(result.current).toEqual({ status: 'done', rows: SEARCH_MC.rows })

    rerender({ text: 'McN' })
    await passDebounce()
    expect(sent.map((s) => s.query)).toEqual(['mc', 'McN'])
    // 'McN' is in flight; typing on aborts it, and its rejection lands.
    await act(async () => {
      rerender({ text: 'McNair' })
      // Flushes the rejection without reaching the next debounce.
      await vi.advanceTimersByTimeAsync(0)
    })
    expect(sent[1]?.signal?.aborted).toBe(true)
    expect(result.current).toEqual({
      status: 'searching',
      rows: SEARCH_MC.rows,
    })

    await passDebounce()
    expect(result.current.status).toBe('searching')
    await act(async () => {
      sent[2]?.resolve(SEARCH_MCNAIR)
      await Promise.resolve()
    })
    expect(result.current).toEqual({
      status: 'done',
      rows: SEARCH_MCNAIR.rows,
    })
  })

  it("sends the group it's given, and asks again when the group changes (#436)", async () => {
    mockedSearch.mockResolvedValue({ ...SEARCH_MCNAIR, rows: [] })
    const { rerender } = renderHook(
      ({ group }: { group: PlayerPositionGroup | undefined }) =>
        usePlayerSearch('faulk', group),
      { initialProps: { group: 'RB' as PlayerPositionGroup | undefined } },
    )
    await passDebounce()
    expect(mockedSearch).toHaveBeenLastCalledWith('faulk', {
      limit: 10,
      signal: expect.any(AbortSignal) as AbortSignal,
      group: 'RB',
    })

    rerender({ group: 'WR' })
    await passDebounce()
    expect(mockedSearch).toHaveBeenCalledTimes(2)
    expect(mockedSearch).toHaveBeenLastCalledWith('faulk', {
      limit: 10,
      signal: expect.any(AbortSignal) as AbortSignal,
      group: 'WR',
    })

    // No group: no group key at all, so the search is unfiltered.
    rerender({ group: undefined })
    await passDebounce()
    expect(mockedSearch).toHaveBeenCalledTimes(3)
    expect(mockedSearch.mock.calls[2]?.[1]).not.toHaveProperty('group')
  })

  it('aborts an in-flight search when the hook unmounts', async () => {
    const sent = recordSearches()
    const { unmount } = renderHook(() => usePlayerSearch('mc'))
    await passDebounce()

    unmount()

    expect(sent[0]?.signal?.aborted).toBe(true)
  })
})
