import { readdirSync } from 'node:fs'
import { resolve, sep } from 'node:path'
import * as a11yAddonAnnotations from '@storybook/addon-a11y/preview'
import {
  composeStories,
  composeStory,
  setProjectAnnotations,
} from '@storybook/react-vite'
import { describe, expect, it } from 'vitest'
import storybookMain from '../../.storybook/main'
import previewAnnotations from '../../.storybook/preview'
import { STORY_A11Y_ALLOWLIST } from './storyA11yAllowlist'

/**
 * Enforces the Storybook a11y gate's rules (issue #90).
 *
 * `npm run test-storybook` fails a story on any axe violation only while that
 * story's *composed* annotations leave axe on and in `'error'` mode. Every
 * opt-out the a11y addon honours, and every way to drop a story from
 * addon-vitest's collection, is a single line in a story file, and none of
 * them fails anything by itself. This test composes every story the way
 * Storybook does (the a11y addon's annotations, then the real
 * `.storybook/preview.tsx`, then meta, then story) and fails on any of those
 * opt-outs, whether it is written literally or computed. It checks values,
 * not source text.
 *
 * What it checks, and why each matters (see the addon-a11y `afterEach` and
 * addon-vitest's `tags.include` default):
 * - composed `tags` include `'test'` -- addon-vitest only collects those, so
 *   `tags: ['!test']` silently drops a story from the run;
 * - `parameters.a11y.test === 'error'` -- `'todo'` only warns, `'off'` skips;
 * - `parameters.a11y.disable` is unset -- `true` skips axe;
 * - `globals.a11y.manual` is not `true` and `globals.ghostStories` is unset --
 *   either one skips axe;
 * - no `a11y.config.rules`, `a11y.context` or `a11y.options.runOnly` -- each
 *   narrows what axe checks;
 * - as a catch-all, composed `parameters.a11y` and `globals.a11y` equal the
 *   project baseline exactly, so a knob not listed above (e.g.
 *   `a11y.options.rules`) can't slip through either.
 *
 * The only exception is an entry in `storyA11yAllowlist.ts`, with a
 * justification.
 */

setProjectAnnotations([a11yAddonAnnotations, previewAnnotations])

/** `.storybook/main.ts`'s `stories`, as this check was written to cover it. */
const COVERED_STORYBOOK_STORIES_GLOBS = [
  '../src/**/*.mdx',
  '../src/**/*.stories.@(js|jsx|mjs|ts|tsx)',
]

type StoryModule = Parameters<typeof composeStories>[0]

// The same file set as the second COVERED_STORYBOOK_STORIES_GLOBS entry,
// written with braces: Vite's `import.meta.glob` silently matches *nothing*
// for the `@(a|b)` extglob form Storybook uses. Relative to `src/test/`, so
// `../**` is all of `src/`, new directories included. The first test below
// cross-checks the result against the filesystem, so a glob that quietly
// stops matching fails instead of policing zero stories.
const storyModules = import.meta.glob<StoryModule>(
  '../**/*.stories.{js,jsx,mjs,ts,tsx}',
  { eager: true },
)

// Vite rewrites `import.meta.url` under test, so resolve from Vitest's cwd
// (`apps/web`), as `src/lib/api/vocabularies.test.ts` does.
const SRC_DIR = resolve(process.cwd(), 'src')
const STORY_FILE = /\.stories\.(js|jsx|mjs|ts|tsx)$/

interface A11yParameters {
  test?: unknown
  disable?: unknown
  context?: unknown
  config?: { rules?: unknown }
  options?: { runOnly?: unknown }
}

interface CollectedStory {
  file: string
  exportName: string
  id: string
  tags: string[]
  a11y: A11yParameters | undefined
  a11yGlobals: { manual?: unknown } | undefined
  ghostStories: unknown
}

interface ComposedStoryShape {
  id: string
  tags: string[]
  parameters: Record<string, unknown>
  globals: Record<string, unknown>
}

function collect(
  file: string,
  exportName: string,
  story: ComposedStoryShape,
): CollectedStory {
  return {
    file,
    exportName,
    id: story.id,
    tags: story.tags,
    a11y: story.parameters.a11y as A11yParameters | undefined,
    a11yGlobals: story.globals.a11y as { manual?: unknown } | undefined,
    ghostStories: story.globals.ghostStories,
  }
}

const collected: CollectedStory[] = Object.entries(storyModules).flatMap(
  ([file, storyModule]) =>
    Object.entries(
      composeStories(storyModule) as Record<string, ComposedStoryShape>,
    ).map(([exportName, story]) => collect(file, exportName, story)),
)

// A story with no annotations of its own: exactly what project annotations
// (the a11y addon + `.storybook/preview.tsx`) give every story.
const baseline = collect(
  '(baseline)',
  'Baseline',
  composeStory(
    {},
    { title: 'story-a11y-policy/baseline' },
  ) as unknown as ComposedStoryShape,
)

const allowlistedIds = new Set(Object.keys(STORY_A11Y_ALLOWLIST))
const policed = collected.filter((story) => !allowlistedIds.has(story.id))

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
      .filter((path) => STORY_FILE.test(path))
      .map((path) => `../${path.split(sep).join('/')}`)
      .sort()
    expect(storyFilesOnDisk.length).toBeGreaterThan(0)
    expect(
      Object.keys(storyModules).sort(),
      'import.meta.glob must collect every story file under src/',
    ).toEqual(storyFilesOnDisk)
    expect(collected.length).toBeGreaterThan(0)
  })

  it('project annotations enforce axe for every story by default', () => {
    expect(baseline.a11y?.test).toBe('error')
    expect(baseline.a11y?.disable).toBeUndefined()
    expect(baseline.a11y?.context).toBeUndefined()
    expect(baseline.a11y?.config?.rules).toBeUndefined()
    expect(baseline.a11y?.options?.runOnly).toBeUndefined()
    expect(baseline.a11yGlobals?.manual).not.toBe(true)
    expect(baseline.ghostStories).toBeFalsy()
    expect(baseline.tags).toContain('test')
  })

  it('story ids are unique, so allowlist entries are unambiguous', () => {
    const ids = collected.map((story) => story.id)
    expect(ids).toEqual([...new Set(ids)])
  })

  it('every allowlist entry names an existing story', () => {
    const ids = new Set(collected.map((story) => story.id))
    const stale = [...allowlistedIds].filter((id) => !ids.has(id))
    expect(stale, 'stale storyA11yAllowlist.ts entries').toEqual([])
  })

  it('every allowlist entry carries a justification', () => {
    const blank = Object.entries(STORY_A11Y_ALLOWLIST)
      .filter(([, justification]) => justification.trim() === '')
      .map(([id]) => id)
    expect(
      blank,
      'storyA11yAllowlist.ts entries with no justification',
    ).toEqual([])
  })

  it.each(policed)(
    '$id ($exportName in $file) keeps axe enforcing',
    (story) => {
      expect(
        story.tags,
        `${story.id}: composed tags must include "test" (addon-vitest skips it otherwise)`,
      ).toContain('test')
      expect(
        story.a11y?.test,
        `${story.id}: parameters.a11y.test must be 'error'`,
      ).toBe('error')
      expect(
        story.a11y?.disable,
        `${story.id}: parameters.a11y.disable must not be set`,
      ).toBeUndefined()
      expect(
        story.a11yGlobals?.manual,
        `${story.id}: globals.a11y.manual must not be true`,
      ).not.toBe(true)
      expect(
        story.ghostStories,
        `${story.id}: globals.ghostStories must not be set`,
      ).toBeFalsy()
      expect(
        story.a11y?.config?.rules,
        `${story.id}: parameters.a11y.config.rules must not be set`,
      ).toBeUndefined()
      expect(
        story.a11y?.context,
        `${story.id}: parameters.a11y.context must not be set`,
      ).toBeUndefined()
      expect(
        story.a11y?.options?.runOnly,
        `${story.id}: parameters.a11y.options.runOnly must not be set`,
      ).toBeUndefined()
      expect(
        story.a11y,
        `${story.id}: parameters.a11y must equal the project baseline`,
      ).toEqual(baseline.a11y)
      expect(
        story.a11yGlobals,
        `${story.id}: globals.a11y must equal the project baseline`,
      ).toEqual(baseline.a11yGlobals)
    },
  )
})
