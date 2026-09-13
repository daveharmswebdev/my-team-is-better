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
      // gate because that script runs in CI. Do not set 'todo'/'off' here or
      // on a story to silence a finding; suppress a single rule, per story,
      // with a comment justifying it as a harness artifact.
      test: 'error',
    },
  },
}

export default preview
