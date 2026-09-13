import { readdirSync, readFileSync } from 'node:fs'
import { resolve, sep } from 'node:path'
import { isDeepStrictEqual } from 'node:util'
import * as a11yAddonAnnotations from '@storybook/addon-a11y/preview'
import {
  composeStories,
  composeStory,
  setProjectAnnotations,
} from '@storybook/react-vite'
import { combineTags } from 'storybook/internal/csf'
import { loadCsf } from 'storybook/internal/csf-tools'
import { describe, expect, it } from 'vitest'
import {
  A11Y_KNOBS,
  STORYBOOK_TEST_OPTIONS,
  STORY_A11Y_EXEMPTIONS,
  STORY_FILE_PATTERN,
  type A11yKnob,
} from '../../.storybook/a11yPolicy'
import storybookMain from '../../.storybook/main'
import previewAnnotations from '../../.storybook/preview'

/**
 * Static half of the Storybook a11y gate (issue #90), in `npm run test`.
 *
 * What this test covers:
 * - each story's annotations, literal or computed, as Storybook composes them
 *   (the a11y addon's annotations, then `.storybook/preview.tsx`, then meta,
 *   then story);
 * - addon-vitest's static CSF parse of each file, compared with the runtime
 *   composed tags;
 * - that `.storybook/main.ts` still loads addon-a11y;
 * - that `storybookTest` gets only the default tag filters.
 * It fails on every knob listed in `.storybook/a11yPolicy.ts` unless an
 * exemption there waives that exact knob. Nothing can waive the `test` tag.
 *
 * What it does NOT cover: anything that changes a story while it runs
 * (loaders, `beforeEach`, decorators, play functions), since composing never
 * runs them. `.storybook/a11y-guard.setup.ts` covers that in
 * `npm run test-storybook`. Stories skipped or never collected by that run
 * are covered by `.storybook/storyRunGuard.ts`.
 */

setProjectAnnotations([a11yAddonAnnotations, previewAnnotations])

/** `.storybook/main.ts` `stories`, as this check was written to cover it. */
const COVERED_STORYBOOK_STORIES_GLOBS = [
  '../src/**/*.mdx',
  '../src/**/*.stories.@(js|jsx|mjs|ts|tsx)',
]

type StoryModule = Parameters<typeof composeStories>[0]

// The same file set as the second COVERED_STORYBOOK_STORIES_GLOBS entry,
// written with braces: Vite's `import.meta.glob` silently matches *nothing*
// for the `@(a|b)` extglob form Storybook uses. Relative to `src/test/`, so
// `../**` is all of `src/`, new directories included. Cross-checked against
// the filesystem below, so a glob that quietly stops matching fails.
const storyModules = import.meta.glob<StoryModule>(
  '../**/*.stories.{js,jsx,mjs,ts,tsx}',
  { eager: true },
)

// Vite rewrites `import.meta.url` under test, so resolve from Vitest's cwd
// (`apps/web`), as `src/lib/api/vocabularies.test.ts` does.
const SRC_DIR = resolve(process.cwd(), 'src')

interface ComposedStoryShape {
  id: string
  tags: string[]
  parameters: Record<string, unknown>
  globals: Record<string, unknown>
}

interface CollectedStory {
  file: string
  exportName: string
  id: string
  tags: string[]
  a11y: unknown
  globals: Record<string, unknown>
}

interface CollectedModule {
  file: string
  stories: CollectedStory[]
  /** Exports addon-vitest's static parse turns into tests. */
  staticTestExports: string[]
  /** Exports whose runtime composed tags include `test`. */
  runtimeTestExports: string[]
}

function collectStory(
  file: string,
  exportName: string,
  story: ComposedStoryShape,
): CollectedStory {
  return {
    file,
    exportName,
    id: story.id,
    tags: story.tags,
    a11y: story.parameters.a11y,
    globals: story.globals,
  }
}

/** Mirrors addon-vitest's `vitestTransform` with the default tag filters. */
function staticTestExports(file: string): string[] {
  const fileName = resolve(SRC_DIR, file.replace(/^\.\.\//, ''))
  const csf = loadCsf(readFileSync(fileName, 'utf8'), {
    fileName,
    makeTitle: (userTitle?: string) => userTitle ?? 'untitled',
  }).parse()
  return Object.entries(csf._stories)
    .filter(([, story]) =>
      combineTags(
        'test',
        'dev',
        ...(previewAnnotations.tags ?? []),
        ...(csf.meta?.tags ?? []),
        ...(story.tags ?? []),
      ).includes('test'),
    )
    .map(([exportName]) => exportName)
    .sort()
}

const collectedModules: CollectedModule[] = Object.entries(storyModules).map(
  ([file, storyModule]) => {
    const stories = Object.entries(
      composeStories(storyModule) as Record<string, ComposedStoryShape>,
    ).map(([exportName, story]) => collectStory(file, exportName, story))
    return {
      file,
      stories,
      staticTestExports: staticTestExports(file),
      runtimeTestExports: stories
        .filter((story) => story.tags.includes('test'))
        .map((story) => story.exportName)
        .sort(),
    }
  },
)
const collected = collectedModules.flatMap((module) => module.stories)

// A story with no annotations of its own: exactly what project annotations
// (the a11y addon + `.storybook/preview.tsx`) give every story.
const baseline = collectStory(
  '(baseline)',
  'Baseline',
  composeStory(
    {},
    { title: 'story-a11y-policy/baseline' },
  ) as unknown as ComposedStoryShape,
)

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

/** `{ id, enabled: true }` only: turns an extra rule on, narrows nothing. */
function isEnablingConfigRule(rule: unknown): boolean {
  return (
    isRecord(rule) &&
    typeof rule.id === 'string' &&
    isDeepStrictEqual(Object.keys(rule).sort(), ['enabled', 'id']) &&
    rule.enabled === true
  )
}

interface KnobFinding {
  knob: A11yKnob
  detail: string
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

const show = (value: unknown) => JSON.stringify(value)

/** Every knob this story uses to weaken the gate, with what it set. */
function findA11yKnobs(story: CollectedStory): KnobFinding[] {
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
  const configRules = prune(config.rules)
  if (
    configRules !== undefined &&
    !(Array.isArray(configRules) && configRules.every(isEnablingConfigRule))
  ) {
    findings.push({
      knob: 'rules',
      detail: `parameters.a11y.config.rules ${show(configRules)} does more than enable extra rules`,
    })
  }
  const optionRules = prune(options.rules)
  if (
    optionRules !== undefined &&
    !(
      isRecord(optionRules) &&
      Object.values(optionRules).every((rule) =>
        isDeepStrictEqual(rule, { enabled: true }),
      )
    )
  ) {
    findings.push({
      knob: 'rules',
      detail: `parameters.a11y.options.rules ${show(optionRules)} does more than enable extra rules`,
    })
  }
  const context = prune(a11y.context)
  if (context !== undefined) {
    findings.push({
      knob: 'context',
      detail: `parameters.a11y.context is ${show(context)}`,
    })
  }
  const runOnly = prune(options.runOnly)
  if (runOnly !== undefined) {
    findings.push({
      knob: 'runOnly',
      detail: `parameters.a11y.options.runOnly is ${show(runOnly)}`,
    })
  }
  const remainder = a11yRemainder(story.a11y)
  if (!isDeepStrictEqual(remainder, a11yRemainder(baseline.a11y))) {
    findings.push({
      knob: 'other',
      detail: `parameters.a11y differs from the project's: ${show(remainder)}`,
    })
  }
  const globalsRemainder = globalsA11yRemainder(story.globals)
  if (
    !isDeepStrictEqual(globalsRemainder, globalsA11yRemainder(baseline.globals))
  ) {
    findings.push({
      knob: 'other',
      detail: `globals.a11y differs from the project's: ${show(globalsRemainder)}`,
    })
  }
  return findings
}

describe('Storybook a11y policy (issue #90)', () => {
  it('covers every story file Storybook collects', () => {
    expect(
      storybookMain.stories,
      'update this check together with `.storybook/main.ts` "stories"',
    ).toEqual(COVERED_STORYBOOK_STORIES_GLOBS)

    const storyFilesOnDisk = readdirSync(SRC_DIR, {
      recursive: true,
      encoding: 'utf8',
    })
      .filter((path) => STORY_FILE_PATTERN.test(path))
      .map((path) => `../${path.split(sep).join('/')}`)
      .sort()
    expect(storyFilesOnDisk.length).toBeGreaterThan(0)
    expect(
      Object.keys(storyModules).sort(),
      'import.meta.glob must collect every story file under src/',
    ).toEqual(storyFilesOnDisk)
  })

  it('.storybook/main.ts loads the a11y addon these checks rely on', () => {
    const addons = (storybookMain.addons ?? []).map((addon) =>
      typeof addon === 'string' ? addon : addon.name,
    )
    expect(addons).toContain('@storybook/addon-a11y')
  })

  it('storybookTest gets only the default tag filters', () => {
    expect(STORYBOOK_TEST_OPTIONS).toStrictEqual({
      tags: { include: ['test'], exclude: [], skip: [] },
    })
  })

  it('project annotations enforce axe for every story by default', () => {
    expect(baseline.tags).toContain('test')
    expect(findA11yKnobs(baseline)).toEqual([])
  })

  it('story ids are unique, so exemptions are unambiguous', () => {
    const ids = collected.map((story) => story.id)
    expect(ids).toEqual([...new Set(ids)])
  })

  it('every exemption names an existing story, specific knobs, and a reason', () => {
    const ids = new Set(collected.map((story) => story.id))
    const problems = Object.entries(STORY_A11Y_EXEMPTIONS).flatMap(
      ([id, exemption]) => [
        ...(ids.has(id) ? [] : [`${id}: no such story (stale exemption)`]),
        ...(exemption.justification.trim() === ''
          ? [`${id}: blank justification`]
          : []),
        ...(exemption.waives.length === 0 ? [`${id}: waives no knob`] : []),
        ...exemption.waives
          .filter((knob) => !(A11Y_KNOBS as readonly string[]).includes(knob))
          .map((knob) => `${id}: unknown knob ${show(knob)}`),
      ],
    )
    expect(problems, '.storybook/a11yPolicy.ts STORY_A11Y_EXEMPTIONS').toEqual(
      [],
    )
  })

  it.each(collectedModules)(
    '$file composes at least one story, and its static tags agree with runtime tags',
    (module) => {
      expect(
        module.stories.length,
        `${module.file}: composes no story (excludeStories/includeStories?)`,
      ).toBeGreaterThan(0)
      expect(
        module.staticTestExports,
        `${module.file}: addon-vitest's static CSF parse would collect different stories than the runtime tags say`,
      ).toEqual(module.runtimeTestExports)
    },
  )

  it.each(collected)(
    '$id ($exportName in $file) keeps axe enforcing',
    (story) => {
      expect(
        story.tags,
        `${story.id}: composed tags must include "test" (addon-vitest skips it otherwise; no exemption can waive this)`,
      ).toContain('test')
      const waived = STORY_A11Y_EXEMPTIONS[story.id]?.waives ?? []
      const unwaived = findA11yKnobs(story)
        .filter((finding) => !waived.includes(finding.knob))
        .map((finding) => `${finding.knob}: ${finding.detail}`)
      expect(
        unwaived,
        `${story.id}: a11y opt-outs with no exemption in .storybook/a11yPolicy.ts`,
      ).toEqual([])
    },
  )
})
