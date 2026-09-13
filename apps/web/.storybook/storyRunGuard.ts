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

/**
 * Run-completeness half of the Storybook a11y gate (issue #90).
 *
 * The a11y checks only protect stories that actually run. Several one-line
 * changes silently drop stories while `npm run test-storybook` stays green:
 * - `storybookTest({ tags: { exclude } })` skips a whole file
 * - `tags: { skip }` skips a test
 * - meta `excludeStories` / `includeStories` leaves a file with no stories
 * - a static `!test` tag with the tags fixed up at run time, which
 *   addon-vitest's static parse never collects
 * - a story file outside the collected globs
 *
 * This reporter fails the run if, after all tests finish:
 * - any story test was skipped, or did not pass or fail;
 * - any collected story file ran no story test;
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

class StoryRunGuardReporter implements Reporter {
  private vitest: VitestWithFilters | undefined

  onInit(vitest: Vitest): void {
    this.vitest = vitest
  }

  onTestRunEnd(
    testModules: ReadonlyArray<TestModule>,
    _unhandledErrors: unknown,
    reason: TestRunEndReason,
  ): void {
    if (reason === 'interrupted' || this.vitest === undefined) {
      return
    }
    const root = this.vitest.config.root
    const problems: string[] = []
    const collected = new Set<string>()

    for (const testModule of testModules) {
      const file = relative(root, testModule.moduleId).split(sep).join('/')
      collected.add(file)
      const tests = [...testModule.children.allTests()]
      if (tests.length === 0) {
        problems.push(
          `${file}: ran no story test (file skipped, or every story excluded or untagged)`,
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
