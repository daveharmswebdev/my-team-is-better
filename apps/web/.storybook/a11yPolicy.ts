/**
 * The Storybook a11y gate's policy (issue #90). Single source of truth for the
 * four checks that enforce it; each covers only what is listed here:
 *
 * - `src/test/storyA11yPolicy.test.ts` (`npm run test`): literal and composed
 *   story annotations (preview + meta + story), static CSF tags against runtime
 *   tags, re-exported stories addon-vitest cannot turn into tests, and that the
 *   lint rule below still exists and fires.
 * - `.storybook/a11y-guard.setup.ts` (`npm run test-storybook`): run-time skips
 *   and narrowing, on the exact `viewMode`, `parameters.a11y` and `globals`
 *   addon-a11y reads (recorded by `.storybook/preview.tsx`'s `afterEach`, after
 *   every story hook), compared with the real project annotations; and that
 *   the a11y report is a single passed result with axe-core's shape.
 * - `eslint.config.js` (`npm run lint`): the syntax, in story files, that
 *   forges a report or changes a11y settings at run time, and vitest /
 *   `.storybook` imports anywhere in non-test `src` (its header lists exactly
 *   which forms remain possible).
 * - `.storybook/storyRunGuard.ts` (`npm run test-storybook`): dropped or partial
 *   story files -- skipped tests, files that ran no test or a different set of
 *   stories than they export, files never collected, tests the guard never saw.
 *
 * This file is imported by the browser-side guard and preview, so it must stay
 * free of Node APIs (the `storybook/browser-side-files` ESLint block enforces
 * that for Node globals).
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

/** A story's a11y-relevant state: `parameters.a11y` and all of `globals`. */
export interface A11yState {
  a11y: unknown
  globals: Record<string, unknown>
}

export interface KnobFinding {
  knob: A11yKnob
  detail: string
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

/** Drops `undefined`, empty objects and empty arrays, recursively. */
function prune(value: unknown): unknown {
  if (Array.isArray(value)) {
    const items = value.map(prune).filter((item) => item !== undefined)
    return items.length > 0 ? items : undefined
  }
  if (isRecord(value)) {
    const entries = Object.entries(value)
      .map(([key, item]) => [key, prune(item)] as const)
      .filter(([, item]) => item !== undefined)
    return entries.length > 0 ? Object.fromEntries(entries) : undefined
  }
  return value
}

/** Structural equality for JSON-like values (functions compare by identity). */
function deepEqual(a: unknown, b: unknown): boolean {
  if (Object.is(a, b)) {
    return true
  }
  if (Array.isArray(a) && Array.isArray(b)) {
    return (
      a.length === b.length &&
      a.every((item, index) => deepEqual(item, b[index]))
    )
  }
  if (isRecord(a) && isRecord(b)) {
    const keys = Object.keys(a)
    return (
      keys.length === Object.keys(b).length &&
      keys.every((key) => key in b && deepEqual(a[key], b[key]))
    )
  }
  return false
}

const show = (value: unknown) => JSON.stringify(value)

/** `{ id, enabled: true }` only: turns an extra rule on, narrows nothing. */
function isEnablingConfigRule(rule: unknown): boolean {
  return (
    isRecord(rule) &&
    typeof rule.id === 'string' &&
    deepEqual(Object.keys(rule).sort(), ['enabled', 'id']) &&
    rule.enabled === true
  )
}

/** An axe run-option rule setting that turns the rule on and nothing else. */
function isEnablingRuleOption(setting: unknown): boolean {
  return deepEqual(setting, { enabled: true })
}

/** The a11y parameters left after removing every key a named knob covers. */
function a11yRemainder(a11y: unknown): unknown {
  if (!isRecord(a11y)) {
    return prune(a11y)
  }
  const rest: Record<string, unknown> = { ...a11y }
  delete rest.test
  delete rest.disable
  delete rest.context
  if (isRecord(rest.config)) {
    rest.config = { ...rest.config, rules: undefined }
  }
  if (isRecord(rest.options)) {
    rest.options = { ...rest.options, runOnly: undefined, rules: undefined }
  }
  return prune(rest)
}

function globalsA11yRemainder(globals: Record<string, unknown>): unknown {
  const a11yGlobals = globals.a11y
  return isRecord(a11yGlobals)
    ? prune({ ...a11yGlobals, manual: undefined })
    : prune(a11yGlobals)
}

/**
 * Every knob `story` uses to weaken the gate, relative to `baseline` (what
 * project annotations give every story).
 */
export function findA11yKnobs(
  story: A11yState,
  baseline: A11yState,
): KnobFinding[] {
  const findings: KnobFinding[] = []
  const a11y = isRecord(story.a11y) ? story.a11y : {}
  const config = isRecord(a11y.config) ? a11y.config : {}
  const options = isRecord(a11y.options) ? a11y.options : {}
  const a11yGlobals = isRecord(story.globals.a11y) ? story.globals.a11y : {}

  if (a11y.test !== 'error') {
    findings.push({
      knob: 'test',
      detail: `parameters.a11y.test is ${show(a11y.test)}, must be 'error'`,
    })
  }
  if (a11y.disable !== undefined && a11y.disable !== false) {
    findings.push({
      knob: 'disable',
      detail: `parameters.a11y.disable is ${show(a11y.disable)}`,
    })
  }
  if (a11yGlobals.manual === true) {
    findings.push({ knob: 'manual', detail: 'globals.a11y.manual is true' })
  }
  if (story.globals.ghostStories) {
    findings.push({
      knob: 'ghostStories',
      detail: `globals.ghostStories is ${show(story.globals.ghostStories)}`,
    })
  }
  // `rules`, `context` and `runOnly` are judged against the baseline, so
  // whatever the project annotations (every addon's defaults included) already
  // set is not the story's doing.
  const baselineA11y = isRecord(baseline.a11y) ? baseline.a11y : {}
  const baselineConfig = isRecord(baselineA11y.config)
    ? baselineA11y.config
    : {}
  const baselineOptions = isRecord(baselineA11y.options)
    ? baselineA11y.options
    : {}

  const configRules = prune(config.rules)
  const baselineConfigRules = prune(baselineConfig.rules)
  const addedConfigRules = Array.isArray(configRules)
    ? configRules.filter(
        (rule) =>
          !isEnablingConfigRule(rule) &&
          !(
            Array.isArray(baselineConfigRules) &&
            baselineConfigRules.some((known) => deepEqual(known, rule))
          ),
      )
    : configRules === undefined || deepEqual(configRules, baselineConfigRules)
      ? []
      : [configRules]
  if (addedConfigRules.length > 0) {
    findings.push({
      knob: 'rules',
      detail: `parameters.a11y.config.rules ${show(addedConfigRules)} does more than enable extra rules`,
    })
  }
  const optionRules = prune(options.rules)
  const baselineOptionRules = prune(baselineOptions.rules)
  const addedOptionRules = isRecord(optionRules)
    ? Object.entries(optionRules).filter(
        ([id, setting]) =>
          !isEnablingRuleOption(setting) &&
          !(
            isRecord(baselineOptionRules) &&
            deepEqual(baselineOptionRules[id], setting)
          ),
      )
    : optionRules === undefined || deepEqual(optionRules, baselineOptionRules)
      ? []
      : [['(not an object)', optionRules]]
  if (addedOptionRules.length > 0) {
    findings.push({
      knob: 'rules',
      detail: `parameters.a11y.options.rules ${show(Object.fromEntries(addedOptionRules))} does more than enable extra rules`,
    })
  }
  const context = prune(a11y.context)
  if (
    context !== undefined &&
    !deepEqual(context, prune(baselineA11y.context))
  ) {
    findings.push({
      knob: 'context',
      detail: `parameters.a11y.context is ${show(context)}`,
    })
  }
  const runOnly = prune(options.runOnly)
  if (
    runOnly !== undefined &&
    !deepEqual(runOnly, prune(baselineOptions.runOnly))
  ) {
    findings.push({
      knob: 'runOnly',
      detail: `parameters.a11y.options.runOnly is ${show(runOnly)}`,
    })
  }
  const remainder = a11yRemainder(story.a11y)
  if (!deepEqual(remainder, a11yRemainder(baseline.a11y))) {
    findings.push({
      knob: 'other',
      detail: `parameters.a11y differs from the project's: ${show(remainder)}`,
    })
  }
  const globalsRemainder = globalsA11yRemainder(story.globals)
  if (!deepEqual(globalsRemainder, globalsA11yRemainder(baseline.globals))) {
    findings.push({
      knob: 'other',
      detail: `globals.a11y differs from the project's: ${show(globalsRemainder)}`,
    })
  }
  return findings
}

/**
 * The story context addon-a11y is about to read, as `.storybook/preview.tsx`'s
 * `afterEach` records it: that hook runs after every story-level hook and play
 * function and immediately before addon-a11y's own `afterEach` (Storybook runs
 * annotation `afterEach` hooks in reverse order).
 *
 * The guard checks these values rather than the axe result's `toolOptions`:
 * the addon derives its run options from exactly these parameters, adding its
 * own defaults (e.g. a disabled `region` rule), so the options add no signal
 * and would only mistake addon defaults for narrowing.
 *
 * Kept on `globalThis` so the recorder and the guard share it whichever module
 * instance each loads. Story code could write it deliberately; the lint rule
 * bans importing `.storybook/*` from `src`.
 */
export interface RecordedStoryA11yContext {
  viewMode: unknown
  a11y: unknown
  globals: Record<string, unknown>
}

const RECORDED_CONTEXTS = Symbol.for(
  'my-team-is-better.a11y-gate.recorded-story-contexts',
)

function recordedContexts(): Map<string, RecordedStoryA11yContext> {
  const holder = globalThis as unknown as Record<
    symbol,
    Map<string, RecordedStoryA11yContext> | undefined
  >
  let contexts = holder[RECORDED_CONTEXTS]
  if (contexts === undefined) {
    contexts = new Map()
    holder[RECORDED_CONTEXTS] = contexts
  }
  return contexts
}

export function recordStoryA11yContext(
  storyId: string,
  context: RecordedStoryA11yContext,
): void {
  recordedContexts().set(storyId, context)
}

/** Returns and forgets the context recorded for `storyId`, if any. */
export function takeStoryA11yContext(
  storyId: string,
): RecordedStoryA11yContext | undefined {
  const contexts = recordedContexts()
  const recorded = contexts.get(storyId)
  contexts.delete(storyId)
  return recorded
}
