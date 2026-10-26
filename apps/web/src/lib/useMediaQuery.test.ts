import { act, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  WIDE_VIEWPORT_QUERY,
  useIsWideViewport,
  useMediaQuery,
} from './useMediaQuery'

/**
 * A controllable `window.matchMedia`: every list it returns reads the same
 * `matches`, and `set()` flips it and fires `change`, as a resize would.
 */
function stubMatchMedia(initial: boolean) {
  let matches = initial
  const listeners = new Set<() => void>()
  const matchMedia = vi.fn((query: string) => ({
    media: query,
    get matches() {
      return matches
    },
    addEventListener: (_type: 'change', listener: () => void) => {
      listeners.add(listener)
    },
    removeEventListener: (_type: 'change', listener: () => void) => {
      listeners.delete(listener)
    },
  }))
  vi.stubGlobal('matchMedia', matchMedia)
  return {
    matchMedia,
    listeners,
    set(next: boolean) {
      matches = next
      for (const listener of listeners) {
        listener()
      }
    },
  }
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('useMediaQuery (issue #474)', () => {
  it('reports whether the query matches now', () => {
    stubMatchMedia(true)
    const { result } = renderHook(() => useMediaQuery('(min-width: 10px)'))
    expect(result.current).toBe(true)
  })

  it('re-renders with the new answer when the query starts or stops matching', () => {
    const media = stubMatchMedia(false)
    const { result } = renderHook(() => useMediaQuery('(min-width: 10px)'))
    expect(result.current).toBe(false)

    act(() => media.set(true))
    expect(result.current).toBe(true)

    act(() => media.set(false))
    expect(result.current).toBe(false)
  })

  it('stops listening on unmount', () => {
    const media = stubMatchMedia(false)
    const { unmount } = renderHook(() => useMediaQuery('(min-width: 10px)'))
    expect(media.listeners.size).toBe(1)
    unmount()
    expect(media.listeners.size).toBe(0)
  })

  it('answers false where there is no matchMedia (phone first)', () => {
    vi.stubGlobal('matchMedia', undefined)
    const { result } = renderHook(() => useMediaQuery('(min-width: 10px)'))
    expect(result.current).toBe(false)
  })

  it('useIsWideViewport asks the wide-viewport query, the modal breakpoint', () => {
    const media = stubMatchMedia(true)
    const { result } = renderHook(() => useIsWideViewport())
    expect(result.current).toBe(true)
    expect(media.matchMedia).toHaveBeenCalledWith(WIDE_VIEWPORT_QUERY)
    expect(WIDE_VIEWPORT_QUERY).toBe('(min-width: 48rem)')
  })
})
