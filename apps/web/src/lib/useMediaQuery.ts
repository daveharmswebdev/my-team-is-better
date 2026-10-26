import { useCallback, useSyncExternalStore } from 'react'

/**
 * The phone/desktop line (issue #474): the same `48rem` the verdict modal
 * switches at, from a full-screen panel to a centered column. Below it a
 * shareable view offers a floating Share button; at or above it, an inline
 * one at the top of the panel.
 */
export const WIDE_VIEWPORT_QUERY = '(min-width: 48rem)'

function hasMatchMedia(): boolean {
  return (
    typeof window !== 'undefined' && typeof window.matchMedia === 'function'
  )
}

/**
 * Whether a CSS media query matches, kept current as it starts or stops
 * matching (a resize, a rotation). Read through `useSyncExternalStore`, so a
 * render never sees a stale answer and there is no effect-then-re-render
 * flash: the first paint is already the right layout.
 *
 * Where there is no `matchMedia` (jsdom), the answer is `false`: phone first.
 */
export function useMediaQuery(query: string): boolean {
  const subscribe = useCallback(
    (onChange: () => void) => {
      if (!hasMatchMedia()) {
        return () => {}
      }
      const list = window.matchMedia(query)
      list.addEventListener('change', onChange)
      return () => list.removeEventListener('change', onChange)
    },
    [query],
  )
  const getSnapshot = () =>
    hasMatchMedia() ? window.matchMedia(query).matches : false
  return useSyncExternalStore(subscribe, getSnapshot, () => false)
}

/** `useMediaQuery(WIDE_VIEWPORT_QUERY)`: true on a desktop-width viewport. */
export function useIsWideViewport(): boolean {
  return useMediaQuery(WIDE_VIEWPORT_QUERY)
}
