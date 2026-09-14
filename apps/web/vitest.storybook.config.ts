import { fileURLToPath } from 'node:url'
import { storybookTest } from '@storybook/addon-vitest/vitest-plugin'
import { playwright } from '@vitest/browser-playwright'
import { defineConfig } from 'vitest/config'
import { STORYBOOK_TEST_OPTIONS } from './.storybook/a11yPolicy.ts'
import { storyRunGuard } from './.storybook/storyRunGuard.ts'

/**
 * Runs every Storybook story as a test in real Chromium (issue #90), so
 * `.storybook/preview.tsx`'s `a11y.test: 'error'` fails the run on any axe
 * violation instead of only surfacing it in the Storybook UI.
 *
 * `.storybook/a11y-guard.setup.ts` fails any story where axe did not actually
 * run in 'error' mode and pass. See `.storybook/a11yPolicy.ts` for how the
 * checks fit together.
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
    // Every other option lives in STORYBOOK_TEST_OPTIONS, where the policy
    // test pins it to the defaults (no tag excluded or skipped).
    storybookTest({
      ...STORYBOOK_TEST_OPTIONS,
      configDir: fileURLToPath(new URL('./.storybook', import.meta.url)),
    }),
    // Fails the run if any story is skipped, filtered out, never collected,
    // or not checked by the a11y guard below.
    storyRunGuard(),
  ],
  test: {
    name: 'storybook',
    setupFiles: ['./.storybook/a11y-guard.setup.ts'],
    browser: {
      enabled: true,
      headless: true,
      provider: playwright(),
      instances: [{ browser: 'chromium' }],
    },
  },
})
