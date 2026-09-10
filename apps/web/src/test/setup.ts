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
