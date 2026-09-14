import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

// `vite.config.ts` runs tests with `globals: false`, so React Testing
// Library's automatic per-test `cleanup()` (which relies on detecting a
// global `afterEach`) does not register itself -- wire it up explicitly so
// components rendered in one test don't leak into the next.
afterEach(() => {
  cleanup()
})

/**
 * jsdom 29 has `HTMLDialogElement` and its reflected `open` property, but no
 * `showModal()` or `close()` (issue #198). This stands in for the part of
 * them a component test can observe: the `open` attribute, and `close`
 * firing a `close` event. It does NOT emulate the top layer, the inert
 * background, the focus trap or the browser's Escape handling -- those only
 * exist in a real browser, where Storybook's tests and the e2e specs cover
 * them.
 */
if (typeof HTMLDialogElement !== 'undefined') {
  const dialogPrototype = HTMLDialogElement.prototype
  if (typeof dialogPrototype.showModal !== 'function') {
    dialogPrototype.showModal = function showModal(this: HTMLDialogElement) {
      this.setAttribute('open', '')
    }
  }
  if (typeof dialogPrototype.close !== 'function') {
    dialogPrototype.close = function close(this: HTMLDialogElement) {
      if (!this.hasAttribute('open')) {
        return
      }
      this.removeAttribute('open')
      this.dispatchEvent(new Event('close'))
    }
  }
}
