// `storybook/preview-api` rather than `@storybook/react-vite`: addon-vitest
// pre-bundles it, so importing it here cannot trigger a mid-run dependency
// re-optimization (which reloads every test file and loses the runner).
import { composeStory } from 'storybook/preview-api'
import { afterEach } from 'vitest'
import {
  A11Y_GUARD_META_KEY,
  AXE_SKIPPING_KNOBS,
  STORY_A11Y_EXEMPTIONS,
  findA11yKnobs,
  takeStoryA11yContext,
  type A11yState,
} from './a11yPolicy.ts'

/**
 * Run-time layer of the Storybook a11y gate (issue #90), registered in
 * `vitest.storybook.config.ts` `test.setupFiles`.
 *
 * What it checks, for every story, after loaders, beforeEach, decorators,
 * play functions and story afterEach hooks have run:
 * - the story context addon-a11y is about to read, as recorded by the
 *   `afterEach` in `.storybook/preview.tsx` (Storybook runs annotation
 *   `afterEach` hooks in reverse, so that one runs after every story hook and
 *   immediately before addon-a11y's): it must exist, its `viewMode` must be
 *   'story' (addon-a11y skips axe otherwise), and its `parameters.a11y` /
 *   `globals` must pass `findA11yKnobs` against the real project annotations
 *   (every addon plus preview, so an addon's own defaults count as baseline);
 * - unless an exemption waives an axe-skipping knob: exactly one a11y report,
 *   status 'passed', whose result names axe-core and has the shape axe
 *   produces (`passes` / `violations` / `incomplete` / `inapplicable` arrays
 *   and a `url`).
 * An exemption waives only the knobs it names; the other knobs are still
 * checked.
 *
 * What it does not stop: this all runs in the same browser realm as story
 * code, so a deliberate forger can still write the recorder's registry or
 * build a report object with axe's full shape. The ESLint rule in
 * `eslint.config.js` bans the syntax for that in story files; anything that
 * gets past both leaves an `eslint-disable` or a root-config edit in review.
 * It also cannot tell that axe passed because nothing had rendered yet.
 *
 * It has to be a Vitest hook: a Storybook annotation `afterEach` added by
 * preview would run before addon-a11y's and see no report yet.
 */

interface A11yReport {
  type: string
  status: string
  result?: {
    testEngine?: { name?: unknown }
    url?: unknown
    passes?: unknown
    violations?: unknown
    incomplete?: unknown
    inapplicable?: unknown
  }
}

interface StoryTaskMeta {
  storyId?: string
  reports?: A11yReport[]
  [A11Y_GUARD_META_KEY]?: boolean
}

interface ComposedBaseline {
  parameters: Record<string, unknown>
  globals: Record<string, unknown>
}

const show = (value: unknown) => JSON.stringify(value)

let projectBaseline: A11yState | undefined

/**
 * What the real project annotations (set by addon-vitest before any test)
 * give a story with no annotations of its own.
 */
function getProjectBaseline(): A11yState {
  if (projectBaseline === undefined) {
    const composed = composeStory(
      {},
      { title: 'a11y-guard/baseline' },
    ) as unknown as ComposedBaseline
    projectBaseline = {
      a11y: composed.parameters.a11y,
      globals: composed.globals,
    }
  }
  return projectBaseline
}

function isAxeResultShape(result: A11yReport['result']): boolean {
  return (
    result !== undefined &&
    result.testEngine?.name === 'axe-core' &&
    typeof result.url === 'string' &&
    Array.isArray(result.passes) &&
    Array.isArray(result.violations) &&
    Array.isArray(result.incomplete) &&
    Array.isArray(result.inapplicable)
  )
}

afterEach((context) => {
  const meta = context.task.meta as StoryTaskMeta
  // Lets `.storybook/storyRunGuard.ts` fail the run if this guard is ever
  // unregistered, rather than every story silently going unguarded.
  meta[A11Y_GUARD_META_KEY] = true

  const storyId = meta.storyId ?? '(no story id)'
  const waives = STORY_A11Y_EXEMPTIONS[storyId]?.waives ?? []
  const problems: string[] = []

  const baseline = getProjectBaseline()
  const baselineA11y = baseline.a11y as { test?: unknown } | undefined
  if (baselineA11y?.test !== 'error') {
    problems.push(
      `project annotations give parameters.a11y.test ${show(baselineA11y?.test)}, must be 'error'`,
    )
  }

  const recorded = takeStoryA11yContext(storyId)
  if (recorded === undefined) {
    problems.push(
      "no story context was recorded by .storybook/preview.tsx's afterEach (removed, or the story never reached afterEach)",
    )
  } else {
    if (recorded.viewMode !== 'story') {
      problems.push(
        `viewMode is ${show(recorded.viewMode)} at afterEach, must be 'story' (addon-a11y skips axe otherwise)`,
      )
    }
    problems.push(
      ...findA11yKnobs(
        { a11y: recorded.a11y, globals: recorded.globals },
        baseline,
      )
        .filter((finding) => !waives.includes(finding.knob))
        .map((finding) => `${finding.knob}: ${finding.detail}`),
    )
  }

  if (!waives.some((knob) => AXE_SKIPPING_KNOBS.includes(knob))) {
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
    if (report !== undefined && !isAxeResultShape(report.result)) {
      problems.push(
        'the a11y report result does not have the shape axe-core produces (testEngine axe-core, url, passes/violations/incomplete/inapplicable arrays)',
      )
    }
  }

  if (problems.length > 0) {
    throw new Error(
      `${storyId}: axe did not run in full, in 'error' mode, and pass at run ` +
        `time (see .storybook/a11yPolicy.ts):\n  - ${problems.join('\n  - ')}`,
    )
  }
})
