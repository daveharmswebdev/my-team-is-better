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
      // No story may opt out: 'todo'/'off', `disable`, `globals.a11y.manual`,
      // a narrowed `config.rules`/`context`/`options`, or a `!test` tag. That
      // rule is checked, not just stated here: src/test/storyA11yPolicy.test.ts
      // (part of `npm run test`) composes every story with this file and fails
      // on any of them. The only way out is an entry in
      // src/test/storyA11yAllowlist.ts, with a justification.
      test: 'error',
    },
  },
}

export default preview
