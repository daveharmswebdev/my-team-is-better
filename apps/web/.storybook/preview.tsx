import type { Preview } from '@storybook/react-vite'
import '../src/styles/tokens.css'
import '../src/index.css'

const preview: Preview = {
  parameters: {
    controls: {
      matchers: {
        color: /(background|color)$/i,
        date: /Date$/i,
      },
    },

    a11y: {
      // 'error': any axe violation fails the story's test. Enforced by
      // `npm run test-storybook` (vitest.storybook.config.ts, which runs every
      // story in headless Chromium via @storybook/addon-vitest) -- issue #90.
      // `npm run build-storybook` does NOT run axe, so this flag is only a
      // gate because that script runs in CI.
      //
      // No story may opt out. Four checks enforce that; each covers only
      // what it names:
      // - src/test/storyA11yPolicy.test.ts (`npm run test`): literal and
      //   composed annotations (this file + meta + story), static vs runtime
      //   tags, re-exported stories, and that the lint rule still fires.
      // - .storybook/a11y-guard.setup.ts (`npm run test-storybook`): run-time
      //   skips AND run-time narrowing -- every story must end with one
      //   passed axe-core report whose options, and whose story's final
      //   parameters/globals, narrow nothing.
      // - eslint.config.js (`npm run lint`): the syntax that forges a report
      //   or mutates a11y settings at run time.
      // - .storybook/storyRunGuard.ts (`npm run test-storybook`): dropped or
      //   partial stories -- skipped, filtered out, never collected, or a file
      //   running fewer stories than it exports.
      // The only way out is a knob-specific, justified exemption in
      // .storybook/a11yPolicy.ts.
      test: 'error',
    },
  },
}

export default preview
