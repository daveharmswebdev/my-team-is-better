import react from '@vitejs/plugin-react'
import { configDefaults, defineConfig } from 'vitest/config'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    globals: false,
    // `e2e/**` holds the Playwright browser-level specs (issue #39, its own
    // `playwright.config.ts`/`testDir`) -- excluded here so Vitest's default
    // `*.spec.ts` include glob doesn't also try to run them as unit tests.
    exclude: [...configDefaults.exclude, 'e2e/**'],
  },
})
