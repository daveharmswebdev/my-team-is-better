import { readdirSync } from 'node:fs'
import { relative, resolve, sep } from 'node:path'
import type { Plugin } from 'vite'
import type {
  Reporter,
  TestModule,
  TestRunEndReason,
  Vitest,
} from 'vitest/node'
import { A11Y_GUARD_META_KEY, STORY_FILE_PATTERN } from './a11yPolicy.ts'
import { readStaticPreviewTags, staticStoryIndex } from './storyIndex.ts'

/**
 * Run-completeness layer of the Storybook a11y gate (issue #90): dropped or
 * partial stories. The a11y checks only protect stories that actually run, and
 * several changes drop stories while `npm run test-storybook` stays green:
 * `storybookTest` tag filters, meta `excludeStories` / `includeStories`,
 * static tags that disagree with runtime tags, re-exported stories
 * (`export { X } from`) that addon-vitest cannot turn into tests, and story
 * files outside the collected globs.
 *
 * After all tests finish, this reporter fails the run if:
 * - any story test was skipped, or did not pass or fail;
 * - any collected story file ran a different set of story tests than its
 *   static CSF index says it exports (`.storybook/storyIndex.ts`), including
 *   none at all;
 * - any story test was not checked by `.storybook/a11y-guard.setup.ts` (the
 *   guard is unregistered);
 * - on an unfiltered run, any `src/**` story file was never collected.
 *
 * It is attached from a plugin's `configureVitest` hook, not `test.reporters`,
 * so passing `--reporter` on the command line cannot drop it.
 */

// `Vitest.filenamePattern` holds the CLI file filters for the current run but
// is marked @internal, so it is absent from Vitest's public types.
type VitestWithFilters = Vitest & { filenamePattern?: string[] }

const sameNames = (a: readonly string[], b: readonly string[]) =>
  a.length === b.length && a.every((name, index) => name === b[index])

class StoryRunGuardReporter implements Reporter {
  private vitest: VitestWithFilters | undefined

  onInit(vitest: Vitest): void {
    this.vitest = vitest
  }

  async onTestRunEnd(
    testModules: ReadonlyArray<TestModule>,
    _unhandledErrors: unknown,
    reason: TestRunEndReason,
  ): Promise<void> {
    if (reason === 'interrupted' || this.vitest === undefined) {
      return
    }
    const root = this.vitest.config.root
    const previewTags = await readStaticPreviewTags(resolve(root, '.storybook'))
    const problems: string[] = []
    const collected = new Set<string>()

    for (const testModule of testModules) {
      const file = relative(root, testModule.moduleId).split(sep).join('/')
      collected.add(file)
      const tests = [...testModule.children.allTests()]

      let expected: string[] = []
      try {
        const index = staticStoryIndex(testModule.moduleId, previewTags)
        expected = index
          .filter((entry) => entry.collected)
          .map((entry) => entry.name)
          .sort()
        for (const entry of index) {
          if (entry.collected && !entry.transformable) {
            problems.push(
              `${file} > ${entry.exportName}: addon-vitest cannot turn this story into a test (re-exported from another file?)`,
            )
          }
        }
      } catch (error) {
        problems.push(
          `${file}: could not index its stories statically: ${String(error)}`,
        )
      }
      const ran = tests.map((test) => test.name).sort()
      if (tests.length === 0) {
        problems.push(
          `${file}: ran no story test (file skipped, or every story excluded or untagged)`,
        )
      } else if (!sameNames(ran, expected)) {
        problems.push(
          `${file}: ran story tests ${JSON.stringify(ran)} but exports ${JSON.stringify(expected)}`,
        )
      }

      for (const test of tests) {
        const state = test.result().state
        if (state !== 'passed' && state !== 'failed') {
          problems.push(`${file} > ${test.name}: ${state}, not run`)
          continue
        }
        const meta = test.meta() as Record<string, unknown>
        if (meta[A11Y_GUARD_META_KEY] !== true) {
          problems.push(
            `${file} > ${test.name}: not checked by .storybook/a11y-guard.setup.ts (is it still in test.setupFiles?)`,
          )
        }
      }
    }

    if (this.vitest.filenamePattern === undefined) {
      const srcDir = resolve(root, 'src')
      for (const path of readdirSync(srcDir, {
        recursive: true,
        encoding: 'utf8',
      })) {
        const file = `src/${path.split(sep).join('/')}`
        if (STORY_FILE_PATTERN.test(file) && !collected.has(file)) {
          problems.push(`${file}: story file was never collected`)
        }
      }
    }

    if (problems.length > 0) {
      process.exitCode = 1
      throw new Error(
        `Storybook story run incomplete -- these stories escaped the a11y gate:\n  ${problems.join('\n  ')}`,
      )
    }
  }
}

export function storyRunGuard(): Plugin {
  return {
    name: 'story-run-guard',
    configureVitest({ vitest }) {
      vitest.config.reporters.push(new StoryRunGuardReporter())
    },
  }
}
