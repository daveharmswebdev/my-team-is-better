/**
 * The Storybook a11y gate's policy (issue #90). Single source of truth for all
 * three checks that enforce it:
 *
 * - `src/test/storyA11yPolicy.test.ts` (in `npm run test`) checks each story's
 *   literal and composed annotations: preview + meta + story, and static CSF
 *   tags against runtime tags.
 * - `.storybook/a11y-guard.setup.ts` (in `npm run test-storybook`) checks at
 *   run time that axe actually ran in 'error' mode and passed, which catches
 *   opt-outs made in loaders, beforeEach, decorators or play functions.
 * - `.storybook/storyRunGuard.ts` (in `npm run test-storybook`) fails the run
 *   when a story file or story test is skipped, empty, never collected, or
 *   never reached the guard.
 */

/**
 * Every way a story can weaken the gate that a check can see. An exemption must
 * name each knob it waives. Dropping the `test` tag is deliberately not a knob:
 * no exemption can waive it.
 *
 * - `test`: `parameters.a11y.test` is not `'error'`
 * - `disable`: `parameters.a11y.disable` is `true`
 * - `manual`: `globals.a11y.manual` is `true`
 * - `ghostStories`: `globals.ghostStories` is set
 * - `rules`: `a11y.config.rules` / `a11y.options.rules` disable or reconfigure
 *   a rule (enabling an extra rule is allowed and needs no exemption)
 * - `context`: `a11y.context` narrows what axe checks
 * - `runOnly`: `a11y.options.runOnly` narrows which rules run
 * - `other`: any other difference from the project's a11y annotations
 */
export const A11Y_KNOBS = [
  'test',
  'disable',
  'manual',
  'ghostStories',
  'rules',
  'context',
  'runOnly',
  'other',
] as const

export type A11yKnob = (typeof A11Y_KNOBS)[number]

/**
 * Knobs that stop axe running in 'error' mode, so the story produces no passed
 * a11y report. Only an exemption waiving one of these lets the run-time guard
 * accept a story without a passed report. Waiving any other knob still requires
 * axe to run and pass.
 */
export const AXE_SKIPPING_KNOBS: readonly A11yKnob[] = [
  'test',
  'disable',
  'manual',
  'ghostStories',
]

export interface A11yExemption {
  /** The specific knob(s) this story is allowed to use. Never empty. */
  readonly waives: readonly A11yKnob[]
  /** Why: a genuine story-harness artifact, not a component defect. */
  readonly justification: string
}

/**
 * The only way a story may escape the gate, keyed by Storybook story id (e.g.
 * `components-teamcombobox--default`). A real component defect gets a GitHub
 * issue and a fix, not an entry here.
 *
 * Kept empty on purpose. The policy test fails on an entry naming a story that
 * no longer exists, an empty `waives`, an unknown knob, or a blank
 * justification.
 */
export const STORY_A11Y_EXEMPTIONS: Readonly<Record<string, A11yExemption>> = {}

/**
 * Every option `vitest.storybook.config.ts` passes to `storybookTest` besides
 * `configDir`, which is a path computed there. The policy test pins this to
 * exactly the defaults: collect every story tagged `test`, exclude and skip
 * none.
 */
export const STORYBOOK_TEST_OPTIONS: {
  tags: { include: string[]; exclude: string[]; skip: string[] }
} = {
  tags: { include: ['test'], exclude: [], skip: [] },
}

/** A story file, by the same extensions as `.storybook/main.ts` `stories`. */
export const STORY_FILE_PATTERN = /\.stories\.(js|jsx|mjs|ts|tsx)$/

/** `task.meta` key the guard sets, so the run guard can prove it ran. */
export const A11Y_GUARD_META_KEY = 'a11yGuardChecked'
