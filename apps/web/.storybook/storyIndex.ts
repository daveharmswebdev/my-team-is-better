import { existsSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { combineTags } from 'storybook/internal/csf'
import { loadCsf, readConfig } from 'storybook/internal/csf-tools'
import { STORYBOOK_TEST_OPTIONS } from './a11yPolicy.ts'

/**
 * Node-only mirror of which stories addon-vitest turns into tests (issue #90).
 * Shared by `src/test/storyA11yPolicy.test.ts` and `.storybook/storyRunGuard.ts`.
 *
 * It follows `vitestTransform` in `storybook/internal/csf-tools`: parse the
 * file statically with `loadCsf`, combine `test`, `dev`, the preview's
 * *static* `tags` (read the way the plugin reads them, with `readConfig`),
 * the meta tags and the story tags, then apply `STORYBOOK_TEST_OPTIONS`.
 * A story whose `_storyStatements` entry is null (e.g. `export { X } from`)
 * is listed but cannot become a test, which addon-vitest only logs as a
 * warning.
 */

export interface StaticStoryEntry {
  exportName: string
  /** The Vitest test name addon-vitest gives this story. */
  name: string
  tags: string[]
  /** Its combined static tags pass the `storybookTest` tag filter. */
  collected: boolean
  /** addon-vitest can generate a test for it (false for re-exports). */
  transformable: boolean
}

const PREVIEW_FILES = [
  'preview.tsx',
  'preview.ts',
  'preview.jsx',
  'preview.js',
  'preview.mjs',
]

/** The preview's `tags`, statically, exactly as addon-vitest reads them. */
export async function readStaticPreviewTags(
  configDir: string,
): Promise<string[]> {
  const previewPath = PREVIEW_FILES.map((file) =>
    resolve(configDir, file),
  ).find((path) => existsSync(path))
  if (previewPath === undefined) {
    return []
  }
  const tags = (await readConfig(previewPath)).getFieldValue<unknown>(['tags'])
  return Array.isArray(tags)
    ? tags.filter((tag): tag is string => typeof tag === 'string')
    : []
}

export function staticStoryIndex(
  fileName: string,
  previewTags: readonly string[],
): StaticStoryEntry[] {
  const csf = loadCsf(readFileSync(fileName, 'utf8'), {
    fileName,
    transformInlineMeta: true,
    makeTitle: (userTitle?: string) => userTitle ?? 'untitled',
  }).parse()
  const { include, exclude } = STORYBOOK_TEST_OPTIONS.tags
  return Object.entries(csf._stories).map(([exportName, story]) => {
    const tags = combineTags(
      'test',
      'dev',
      ...previewTags,
      ...(csf.meta?.tags ?? []),
      ...(story.tags ?? []),
    )
    return {
      exportName,
      name: story.name ?? exportName,
      tags,
      collected:
        include.some((tag) => tags.includes(tag)) &&
        !exclude.some((tag) => tags.includes(tag)),
      transformable: csf._storyStatements[exportName] != null,
    }
  })
}
