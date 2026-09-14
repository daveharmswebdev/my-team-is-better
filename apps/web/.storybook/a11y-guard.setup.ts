import { afterEach } from 'vitest'
import {
  A11Y_GUARD_META_KEY,
  AXE_SKIPPING_KNOBS,
  STORY_A11Y_EXEMPTIONS,
  findA11yKnobs,
  findAxeRunNarrowing,
  type A11yState,
} from './a11yPolicy.ts'
import previewAnnotations from './preview.tsx'

/**
 * Run-time layer of the Storybook a11y gate (issue #90), registered in
 * `vitest.storybook.config.ts` `test.setupFiles`.
 *
 * What it catches, after loaders, beforeEach, decorators and play functions
 * have run:
 * - run-time skips: the story must end with exactly one a11y report, produced
 *   by axe-core, with status 'passed' ('todo', disable, manual, ghostStories
 *   or a missing @storybook/addon-a11y all leave none, or a non-passed one);
 * - run-time narrowing: the axe result's `toolOptions` must show no `runOnly`
 *   and no rules beyond enabling extra ones, and the story's final
 *   `parameters.a11y` / `globals` (addon-vitest's `context.story`, the same
 *   objects those hooks mutate) must pass `findA11yKnobs`.
 * `STORY_A11Y_EXEMPTIONS` waives only the knobs an entry names.
 *
 * What it does not catch: a report or story state forged from story code in
 * the same browser realm (e.g. through `reporting` or a vitest hook). The lint
 * rule in `eslint.config.js` covers that syntax. It also cannot tell that axe
 * passed because nothing had rendered yet.
 *
 * It has to be a Vitest hook, not a `preview.tsx` `afterEach`. Storybook runs
 * annotation `afterEach` hooks in reverse order, so a preview hook would run
 * before addon-a11y's and see no report yet.
 */

interface A11yReport {
  type: string
  status: string
  result?: { testEngine?: { name?: unknown }; toolOptions?: unknown }
}

interface StoryTaskMeta {
  storyId?: string
  reports?: A11yReport[]
  [A11Y_GUARD_META_KEY]?: boolean
}

interface StoryContextShape {
  parameters?: Record<string, unknown>
  globals?: Record<string, unknown>
}

const PROJECT_BASELINE: A11yState = {
  a11y: previewAnnotations.parameters?.a11y,
  globals: {},
}

afterEach((context) => {
  const meta = context.task.meta as StoryTaskMeta
  // Lets `.storybook/storyRunGuard.ts` fail the run if this guard is ever
  // unregistered, rather than every story silently going unguarded.
  meta[A11Y_GUARD_META_KEY] = true

  const storyId = meta.storyId ?? '(no story id)'
  const waives = STORY_A11Y_EXEMPTIONS[storyId]?.waives ?? []
  if (waives.some((knob) => AXE_SKIPPING_KNOBS.includes(knob))) {
    return
  }

  const problems: string[] = []
  const a11yReports = (meta.reports ?? []).filter(
    (report) => report.type === 'a11y',
  )
  if (a11yReports.length !== 1) {
    problems.push(
      `expected exactly one a11y report, found ${a11yReports.length}`,
    )
  }
  const report = a11yReports[0]
  if (report?.status !== 'passed') {
    problems.push(
      `a11y report status is ${report?.status ?? 'none'}, must be 'passed'`,
    )
  }
  if (report !== undefined && report.result?.testEngine?.name !== 'axe-core') {
    problems.push('the a11y report was not produced by axe-core')
  }

  // Set by addon-vitest's test body; not part of Vitest's TestContext type.
  const story = (context as unknown as { story?: StoryContextShape }).story
  const findings = [
    ...findAxeRunNarrowing(report?.result?.toolOptions),
    ...(story === undefined
      ? [
          {
            knob: 'other' as const,
            detail: 'addon-vitest provided no story context',
          },
        ]
      : findA11yKnobs(
          { a11y: story.parameters?.a11y, globals: story.globals ?? {} },
          PROJECT_BASELINE,
        )),
  ]
  problems.push(
    ...findings
      .filter((finding) => !waives.includes(finding.knob))
      .map((finding) => `${finding.knob}: ${finding.detail}`),
  )

  if (problems.length > 0) {
    throw new Error(
      `${storyId}: axe did not run in full, in 'error' mode, and pass at run ` +
        `time (see .storybook/a11yPolicy.ts):\n  - ${problems.join('\n  - ')}`,
    )
  }
})
