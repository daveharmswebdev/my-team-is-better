import { afterEach } from 'vitest'
import {
  A11Y_GUARD_META_KEY,
  AXE_SKIPPING_KNOBS,
  STORY_A11Y_EXEMPTIONS,
} from './a11yPolicy.ts'

/**
 * Run-time half of the Storybook a11y gate (issue #90), registered in
 * `vitest.storybook.config.ts` `test.setupFiles`.
 *
 * `src/test/storyA11yPolicy.test.ts` can only see annotations as composed
 * before a story runs. Loaders, `beforeEach`, decorators and play functions
 * run later and can still turn axe off: they can mutate `parameters.a11y` or
 * `globals` before addon-a11y's own `afterEach` reads them. So can dropping
 * `@storybook/addon-a11y` from `.storybook/main.ts`. Every one of those
 * leaves the story with no `{ type: 'a11y', status: 'passed' }` report. This
 * hook fails any such story unless `STORY_A11Y_EXEMPTIONS` waives a knob that
 * stops axe running for it.
 *
 * It has to be a Vitest hook, not a `preview.tsx` `afterEach`. Storybook
 * runs annotation `afterEach` hooks in reverse order, so a preview hook would
 * run before addon-a11y's and see no report yet. A Vitest setup-file
 * `afterEach` runs after addon-vitest's test body has copied the story's
 * reports into `task.meta.reports`.
 */

interface StoryTaskMeta {
  storyId?: string
  reports?: { type: string; status: string }[]
  [A11Y_GUARD_META_KEY]?: boolean
}

afterEach(({ task }) => {
  const meta = task.meta as StoryTaskMeta
  // Lets `.storybook/storyRunGuard.ts` fail the run if this guard is ever
  // unregistered, rather than every story silently going unguarded.
  meta[A11Y_GUARD_META_KEY] = true

  const storyId = meta.storyId ?? '(no story id)'
  const waives = STORY_A11Y_EXEMPTIONS[storyId]?.waives ?? []
  if (waives.some((knob) => AXE_SKIPPING_KNOBS.includes(knob))) {
    return
  }

  const a11yReport = meta.reports?.find((report) => report.type === 'a11y')
  if (a11yReport?.status !== 'passed') {
    throw new Error(
      `${storyId}: axe did not run in 'error' mode and pass (a11y report: ${
        a11yReport?.status ?? 'none'
      }). Something turned the a11y check off for this story at run time: ` +
        `a loader, beforeEach, decorator or play function changing ` +
        `parameters.a11y / globals, or @storybook/addon-a11y missing from ` +
        `.storybook/main.ts. See .storybook/a11yPolicy.ts.`,
    )
  }
})
