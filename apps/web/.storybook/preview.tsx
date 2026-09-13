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
      // No story may opt out. Three checks enforce that; each covers only
      // what it names:
      // - src/test/storyA11yPolicy.test.ts (`npm run test`): literal and
      //   composed annotations (this file + meta + story) and static vs
      //   runtime tags.
      // - .storybook/a11y-guard.setup.ts (`npm run test-storybook`): run-time
      //   skips (loaders, beforeEach, decorators, play functions, a missing
      //   addon-a11y) -- every story must end with a passed axe report.
      // - .storybook/storyRunGuard.ts (`npm run test-storybook`): stories
      //   skipped, filtered out or never collected.
      // The only way out is a knob-specific, justified exemption in
      // .storybook/a11yPolicy.ts.
      test: 'error',
    },
  },
}

export default preview
