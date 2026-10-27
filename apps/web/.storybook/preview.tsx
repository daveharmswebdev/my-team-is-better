import type { Preview } from '@storybook/react-vite'
import '../src/styles/tokens.css'
// The app's @font-face rules (issue #408), so stories paint in Anton and
// Barlow; main.ts's staticDirs serves the /fonts/*.woff2 files they point at.
import '../src/styles/fonts.css'
import '../src/index.css'
import { mswLoader } from 'msw-storybook-addon/csf3'
import { recordStoryA11yContext } from './a11yPolicy.ts'

const preview: Preview = {
  // Issue #221: stories fake `apps/api` with the same MSW handlers the unit
  // tests use (src/mocks/handlers.ts). The loader starts the service worker
  // once, resets its handlers before every story, then installs that story's
  // `parameters.msw.handlers`; a request no handler answers is warned about
  // and goes to the network. Handlers are keyed by name, so a story replaces
  // one group (say `verdict`) and keeps the rest of its meta's.
  loaders: [mswLoader()],

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
      // Stories should not opt out. Four checks enforce that, each only for
      // what it names (see .storybook/a11yPolicy.ts):
      // - src/test/storyA11yPolicy.test.ts (`npm run test`): literal and
      //   composed annotations (this file + meta + story), static vs runtime
      //   tags, re-exported stories, and that the lint rules still fire.
      // - .storybook/a11y-guard.setup.ts (`npm run test-storybook`): run-time
      //   skips and narrowing, on the viewMode / parameters / globals the
      //   afterEach below records, plus a single passed axe-core-shaped
      //   report.
      // - eslint.config.js (`npm run lint`): the story-file syntax that forges
      //   a report or changes a11y settings at run time.
      // - .storybook/storyRunGuard.ts (`npm run test-storybook`): dropped or
      //   partial stories.
      // The only sanctioned way out is a knob-specific, justified exemption in
      // .storybook/a11yPolicy.ts.
      test: 'error',
    },
  },

  // Runs after every story-level hook and play function, and immediately
  // before addon-a11y's afterEach (annotation afterEach hooks run in reverse):
  // records what addon-a11y is about to read, for the run-time guard.
  afterEach: ({ id, viewMode, parameters, globals }) => {
    recordStoryA11yContext(id, { viewMode, a11y: parameters.a11y, globals })
  },
}

export default preview
