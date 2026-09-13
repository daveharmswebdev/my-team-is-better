import { fileURLToPath } from 'node:url'
import { storybookTest } from '@storybook/addon-vitest/vitest-plugin'
import { playwright } from '@vitest/browser-playwright'
import { defineConfig } from 'vitest/config'

/**
 * Runs every Storybook story as a test in real Chromium (issue #90), so
 * `.storybook/preview.tsx`'s `a11y.test: 'error'` fails the run on any axe
 * violation instead of only surfacing it in the Storybook UI.
 *
 * Deliberately a separate config file rather than a second `test.projects`
 * entry in `vite.config.ts`: `npm run test` (plain `vitest run`, jsdom, runs
 * in CI before any browser is installed) must keep loading only the unit
 * suite. This file is selected explicitly by `npm run test-storybook`.
 */
export default defineConfig({
  plugins: [
    // Collects stories from `.storybook/main.ts`'s `stories` globs and applies
    // `.storybook/preview.tsx`'s annotations (including the a11y addon).
    storybookTest({
      configDir: fileURLToPath(new URL('./.storybook', import.meta.url)),
    }),
  ],
  test: {
    name: 'storybook',
    browser: {
      enabled: true,
      headless: true,
      provider: playwright(),
      instances: [{ browser: 'chromium' }],
    },
  },
})
