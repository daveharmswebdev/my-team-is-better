import { readdirSync } from 'node:fs'
import { resolve, sep } from 'node:path'
import * as a11yAddonAnnotations from '@storybook/addon-a11y/preview'
import {
  composeStories,
  composeStory,
  setProjectAnnotations,
} from '@storybook/react-vite'
import { ESLint } from 'eslint'
import { describe, expect, it } from 'vitest'
import {
  A11Y_KNOBS,
  STORYBOOK_TEST_OPTIONS,
  STORY_A11Y_EXEMPTIONS,
  STORY_FILE_PATTERN,
  findA11yKnobs,
  type A11yState,
} from '../../.storybook/a11yPolicy'
import storybookMain from '../../.storybook/main'
import previewAnnotations from '../../.storybook/preview'
import {
  readStaticPreviewTags,
  staticStoryIndex,
} from '../../.storybook/storyIndex'

/**
 * Static layer of the Storybook a11y gate (issue #90), in `npm run test`.
 *
 * What this test catches:
 * - literal and composed story annotations (the a11y addon's annotations,
 *   then `.storybook/preview.tsx`, then meta, then story), for every knob in
 *   `.storybook/a11yPolicy.ts` not waived by an exemption; nothing waives the
 *   `test` tag;
 * - addon-vitest's static view of each file (`.storybook/storyIndex.ts`,
 *   preview tags read statically) against the runtime composed tags, and
 *   re-exported stories it cannot turn into tests;
 * - that `.storybook/main.ts` loads addon-a11y, that `storybookTest` gets only
 *   the default tag filters, and that the `eslint.config.js` a11y rule still
 *   exists and rejects forgery and mutation syntax.
 *
 * What it does NOT catch: anything that changes a story while it runs, since
 * composing never runs loaders, beforeEach, decorators or play functions.
 * `.storybook/a11y-guard.setup.ts` covers run-time skips and narrowing, the
 * lint rule covers the syntax for them, and `.storybook/storyRunGuard.ts`
 * covers dropped or partial stories.
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
const WEB_DIR = process.cwd()
const SRC_DIR = resolve(WEB_DIR, 'src')
const staticPreviewTags = await readStaticPreviewTags(
  resolve(WEB_DIR, '.storybook'),
)

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
  state: A11yState
}

interface CollectedModule {
  file: string
  stories: CollectedStory[]
  /** Exports addon-vitest's static parse turns into tests. */
  staticTestExports: string[]
  /** Exports whose runtime composed tags include `test`. */
  runtimeTestExports: string[]
  /** Collected exports addon-vitest cannot generate a test for. */
  untransformable: string[]
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
    state: { a11y: story.parameters.a11y, globals: story.globals },
  }
}

const collectedModules: CollectedModule[] = Object.entries(storyModules).map(
  ([file, storyModule]) => {
    const stories = Object.entries(
      composeStories(storyModule) as Record<string, ComposedStoryShape>,
    ).map(([exportName, story]) => collectStory(file, exportName, story))
    const index = staticStoryIndex(
      resolve(SRC_DIR, file.replace(/^\.\.\//, '')),
      staticPreviewTags,
    ).filter((entry) => entry.collected)
    return {
      file,
      stories,
      staticTestExports: index.map((entry) => entry.exportName).sort(),
      runtimeTestExports: stories
        .filter((story) => story.tags.includes('test'))
        .map((story) => story.exportName)
        .sort(),
      untransformable: index
        .filter((entry) => !entry.transformable)
        .map((entry) => entry.exportName),
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

const show = (value: unknown) => JSON.stringify(value)

/**
 * Story code the `eslint.config.js` a11y rule must reject: each is a form
 * that forges a passed a11y report or changes a11y settings at run time.
 */
const FORBIDDEN_STORY_CODE: [string, string][] = [
  ['imports vitest', "import { afterEach } from 'vitest'\nvoid afterEach\n"],
  [
    'imports an @vitest package',
    "import { page } from '@vitest/browser/context'\nvoid page\n",
  ],
  [
    'dynamically imports vitest',
    "export const load = () => import('vitest')\n",
  ],
  [
    'destructures reporting from a story context',
    'export const S = { play: async ({ reporting }: { reporting: unknown }) => { void reporting } }\n',
  ],
  [
    'reads context.reporting',
    'export const S = { play: async (context: { reporting: unknown }) => { void context.reporting } }\n',
  ],
  [
    'assigns parameters.a11y (N1)',
    'export const S = { beforeEach: ({ parameters }: { parameters: Record<string, unknown> }) => { parameters.a11y = { context: { exclude: ["img"] } } } }\n',
  ],
  [
    'assigns under parameters.a11y through a cast',
    'export const S = { play: async ({ parameters }: { parameters: Record<string, unknown> }) => { (parameters.a11y as { disable?: boolean }).disable = true } }\n',
  ],
  [
    "assigns parameters['a11y']",
    "export const S = { play: async ({ parameters }: { parameters: Record<string, unknown> }) => { parameters['a11y'] = {} } }\n",
  ],
  [
    'aliases parameters.a11y',
    'export const S = { play: async ({ parameters }: { parameters: Record<string, unknown> }) => { const settings = parameters.a11y; void settings } }\n',
  ],
  [
    'destructures a11y',
    'export const S = { play: async ({ parameters }: { parameters: Record<string, unknown> }) => { const { a11y } = parameters; void a11y } }\n',
  ],
  [
    'assigns ctx.globals.a11y (decorator)',
    'export const S = { decorators: [(Story: () => null, ctx: { globals: Record<string, unknown> }) => { ctx.globals.a11y = { manual: true }; return Story() }] }\n',
  ],
  [
    'assigns globals.ghostStories',
    'export const S = { loaders: [async ({ globals }: { globals: Record<string, unknown> }) => { globals.ghostStories = true }] }\n',
  ],
  [
    'Object.assign on parameters with a11y',
    'export const S = { play: async ({ parameters }: { parameters: Record<string, unknown> }) => { Object.assign(parameters, { a11y: { test: "off" } }) } }\n',
  ],
  [
    'Object.assign on ctx.globals',
    'export const S = { play: async (ctx: { globals: Record<string, unknown> }) => { Object.assign(ctx.globals, { manual: true }) } }\n',
  ],
  [
    'reassigns ctx.parameters',
    'export const S = { play: async (ctx: { parameters: Record<string, unknown> }) => { ctx.parameters = { ...ctx.parameters } } }\n',
  ],
  [
    'deletes under parameters.a11y',
    'export const S = { play: async ({ parameters }: { parameters: { a11y: { test?: string } } }) => { delete parameters.a11y.test } }\n',
  ],
]

/** Ordinary story code the rule must leave alone. */
const ORDINARY_STORY_CODE = `import type { Meta, StoryObj } from '@storybook/react-vite'
import { createElement } from 'react'
import { expect, fn, userEvent, within } from 'storybook/test'

const meta = {
  title: 'probe/Ordinary',
  args: { onClick: fn() },
  parameters: { a11y: { config: { rules: [{ id: 'p-as-heading', enabled: true }] } } },
  render: (args) => createElement('button', { type: 'button', onClick: args.onClick }, 'Go'),
} satisfies Meta<{ onClick: () => void }>

export default meta

export const Default: StoryObj<typeof meta> = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement)
    await userEvent.click(canvas.getByRole('button', { name: 'Go' }))
    await expect(args.onClick).toHaveBeenCalled()
  },
}
`

const A11Y_LINT_RULES = ['no-restricted-syntax', 'no-restricted-imports']
const PROBE_FILE = 'src/zzlintprobe/Probe.stories.ts'

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

  it("the preview's static tags (what addon-vitest reads) equal its runtime tags", () => {
    expect(staticPreviewTags).toEqual(previewAnnotations.tags ?? [])
  })

  it('project annotations enforce axe for every story by default', () => {
    expect(baseline.tags).toContain('test')
    expect(findA11yKnobs(baseline.state, baseline.state)).toEqual([])
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
    expect(
      problems,
      `.storybook/a11yPolicy.ts STORY_A11Y_EXEMPTIONS: ${problems.join('; ')}`,
    ).toEqual([])
  })

  it.each(collectedModules)(
    '$file composes at least one story, every one addon-vitest can test, with static tags matching runtime tags',
    (module) => {
      expect(
        module.stories.length,
        `${module.file}: composes no story (excludeStories/includeStories?)`,
      ).toBeGreaterThan(0)
      expect(
        module.untransformable,
        `${module.file}: addon-vitest cannot turn these stories into tests (re-exported with \`export { X } from\`? define them in the story file)`,
      ).toEqual([])
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
      const unwaived = findA11yKnobs(story.state, baseline.state)
        .filter((finding) => !waived.includes(finding.knob))
        .map((finding) => `${finding.knob}: ${finding.detail}`)
      expect(
        unwaived,
        `${story.id}: a11y opt-outs with no exemption in .storybook/a11yPolicy.ts: ${unwaived.join('; ')}`,
      ).toEqual([])
    },
  )

  describe('eslint.config.js a11y rule', () => {
    const eslint = new ESLint({ cwd: WEB_DIR })

    it('is configured as an error for story files, including new directories', async () => {
      for (const file of [
        'src/components/AppShell/AppShell.stories.tsx',
        PROBE_FILE,
      ]) {
        const config = (await eslint.calculateConfigForFile(file)) as {
          rules?: Record<string, unknown>
        }
        for (const rule of A11Y_LINT_RULES) {
          const setting = config.rules?.[rule]
          const severity = Array.isArray(setting) ? setting[0] : setting
          expect(
            severity,
            `${file}: ${rule} must be an error (eslint.config.js)`,
          ).toBe(2)
        }
      }
    })

    it.each(FORBIDDEN_STORY_CODE)(
      'rejects story code that %s',
      async (_description, code) => {
        const [result] = await eslint.lintText(code, { filePath: PROBE_FILE })
        const hits = (result?.messages ?? []).filter((message) =>
          A11Y_LINT_RULES.includes(message.ruleId ?? ''),
        )
        expect(
          hits.length,
          `no ${A11Y_LINT_RULES.join('/')} error for:\n${code}\nmessages: ${show(result?.messages)}`,
        ).toBeGreaterThan(0)
      },
    )

    it('leaves ordinary story code alone', async () => {
      const [result] = await eslint.lintText(ORDINARY_STORY_CODE, {
        filePath: PROBE_FILE,
      })
      expect(
        (result?.messages ?? []).filter((message) =>
          A11Y_LINT_RULES.includes(message.ruleId ?? ''),
        ),
      ).toEqual([])
    })
  })
})
