import { WIDE_VIEWPORT_QUERY } from '../lib/useMediaQuery'

/** The two layouts the app switches between at `WIDE_VIEWPORT_QUERY` (issue #474). */
export type Viewport = 'phone' | 'desktop'

/**
 * A `window.matchMedia` (jsdom has none) that answers as a phone or a
 * desktop would: `WIDE_VIEWPORT_QUERY` matches only on a desktop, and every
 * other query -- the rating disclosures' touch-pointer one -- only on a
 * phone. Install it with `vi.stubGlobal('matchMedia', matchMediaFor(...))`
 * (this file can't import vitest: only test files may, per eslint.config.js).
 */
export function matchMediaFor(
  viewport: Viewport,
): (query: string) => MediaQueryList {
  const noop = () => {}
  return (query) =>
    ({
      matches:
        query === WIDE_VIEWPORT_QUERY
          ? viewport === 'desktop'
          : viewport === 'phone',
      media: query,
      onchange: null,
      addEventListener: noop,
      removeEventListener: noop,
      addListener: noop,
      removeListener: noop,
      dispatchEvent: () => false,
    }) satisfies MediaQueryList
}

/** Asserts each element comes after the one before it in document (reading) order. */
export function expectReadingOrder(...elements: Element[]) {
  const outOfOrder = elements.flatMap((element, index) => {
    const previous = elements[index - 1]
    return previous !== undefined &&
      !(
        previous.compareDocumentPosition(element) &
        Node.DOCUMENT_POSITION_FOLLOWING
      )
      ? [`#${index - 1} -> #${index}`]
      : []
  })
  if (outOfOrder.length > 0) {
    throw new Error(
      `Elements out of reading order at ${outOfOrder.join(', ')}:\n${elements
        .map(
          (element, index) => `#${index}: ${element.outerHTML.slice(0, 120)}`,
        )
        .join('\n')}`,
    )
  }
}
