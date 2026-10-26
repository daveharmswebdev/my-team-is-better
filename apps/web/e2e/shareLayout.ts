import { expect } from './fixtures.ts'
import type { Locator, Page } from '@playwright/test'

// Issue #474's share layouts, measured in a real browser. On a phone the
// Share button floats bottom-right over the scrolling modal (a FAB); on a
// desktop it is an inline button at the top of the panel. A component test
// can pin the DOM order, but only a browser can say where the button paints.

/** A phone, the size `share.spec.ts` and `player-compare.spec.ts` already use. */
export const PHONE = { width: 390, height: 844 }

/** The material-design FAB size, and the floor the founder set (#474). */
const FAB_MIN_SIZE = 56

// Browser-side snippets: self-contained, since Playwright ships their source.
const scrollModalToBottom = () => {
  const modal = document.querySelector('dialog[open]')
  if (modal === null) throw new Error('no open dialog')
  modal.scrollTop = modal.scrollHeight
  return modal.scrollTop
}
const readLastLineAndShare = () => {
  const slot = document.querySelector('dialog[open] [data-layout="floating"]')
  const button = slot?.querySelector('button')
  const last = slot?.previousElementSibling
  if (!button || !last) throw new Error('no floating share slot')
  return {
    lastLineBottom: last.getBoundingClientRect().bottom,
    shareTop: button.getBoundingClientRect().top,
    position: getComputedStyle(button.parentElement ?? button).position,
  }
}

// The whole floating stack -- button, toast, manual-copy box -- against the
// content's last line, at the bottom of the scroll.
const readLastLineAndOverlay = () => {
  const modal = document.querySelector('dialog[open]')
  if (modal === null) throw new Error('no open dialog')
  modal.scrollTop = modal.scrollHeight
  const slot = modal.querySelector('[data-layout="floating"]')
  const stack = slot?.firstElementChild
  const last = slot?.previousElementSibling
  if (!stack || !last) throw new Error('no floating share slot')
  return {
    lastLineBottom: last.getBoundingClientRect().bottom,
    overlayTop: stack.getBoundingClientRect().top,
  }
}

/** Makes the clipboard refuse, so ShareButton falls back to the manual-copy box. */
export const refuseClipboard = () => {
  Object.defineProperty(Navigator.prototype, 'share', {
    value: undefined,
    configurable: true,
  })
  Object.defineProperty(Navigator.prototype, 'clipboard', {
    value: {
      writeText: () => Promise.reject(new Error('Clipboard blocked')),
    },
    configurable: true,
  })
}

/**
 * Issue #474, round 2: whatever the floating stack shows -- the toast or the
 * manual-copy box -- scrolled to the bottom, the content's last line ends
 * above it rather than under it.
 */
export async function expectOverlayClearOfLastLine(page: Page) {
  await expect
    .poll(async () => {
      const { lastLineBottom, overlayTop } = await page.evaluate(
        readLastLineAndOverlay,
      )
      return lastLineBottom <= overlayTop
    })
    .toBe(true)
}

/** Whether `first` comes before `second` in document (reading) order. */
export async function precedes(first: Locator, second: Locator) {
  const handle = await second.elementHandle()
  return first.evaluate(
    (element, other) =>
      other !== null &&
      (element.compareDocumentPosition(other) &
        Node.DOCUMENT_POSITION_FOLLOWING) !==
        0,
    handle,
  )
}

/**
 * On a phone: the Share button is on screen with no scrolling, at least
 * 56x56, still on screen after scrolling the modal to the bottom, and there
 * it sits below the content's last line rather than over it.
 */
export async function expectFloatingShare(page: Page, share: Locator) {
  await expect(share).toBeInViewport({ ratio: 1 })
  const box = await share.boundingBox()
  expect(box?.width).toBeGreaterThanOrEqual(FAB_MIN_SIZE)
  expect(box?.height).toBeGreaterThanOrEqual(FAB_MIN_SIZE)
  // Bottom-right: its right and bottom edges sit near the screen's.
  const viewport = page.viewportSize()
  expect(viewport).not.toBeNull()
  if (box !== null && viewport !== null) {
    expect(viewport.width - (box.x + box.width)).toBeLessThanOrEqual(32)
    expect(viewport.height - (box.y + box.height)).toBeLessThanOrEqual(48)
  }

  await page.evaluate(scrollModalToBottom)
  await expect(share).toBeInViewport({ ratio: 1 })
  const { lastLineBottom, shareTop, position } =
    await page.evaluate(readLastLineAndShare)
  expect(position).toBe('fixed')
  expect(lastLineBottom).toBeLessThanOrEqual(shareTop)
}

/** On a desktop: an inline button, never fixed, with no floating one anywhere. */
export async function expectInlineShare(page: Page, share: Locator) {
  await expect(share).toBeVisible()
  await expect(
    page.locator('dialog[open] [data-layout="floating"]'),
  ).toHaveCount(0)
  expect(
    await share.evaluate((button) => {
      for (
        let element: Element | null = button;
        element !== null;
        element = element.parentElement
      ) {
        if (getComputedStyle(element).position === 'fixed') {
          return element.tagName !== 'DIALOG'
        }
      }
      return false
    }),
  ).toBe(false)
}
