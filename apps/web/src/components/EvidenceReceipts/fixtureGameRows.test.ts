import { readdirSync } from 'node:fs'
import { relative, resolve, sep } from 'node:path'
import { describe, expect, it } from 'vitest'
import { STORY_FILE_PATTERN } from '../../../.storybook/a11yPolicy'
import {
  VENUES,
  collectGameRows,
  venueProblems,
  type CollectedGameRow,
} from '../../test/gameRowVenue'

/**
 * Every game row a story fixture builds has to be a row the API could
 * actually send (issue #294): `venue` is this team's own side, and on an
 * `OpponentResultOut` it agrees with `neutral_site`, because the engine
 * refuses to build a pair that disagrees. TypeScript makes `venue` required
 * but cannot see that a row saying `neutral_site: false, venue: 'neutral'`
 * is a lie, so this check does -- and it covers new story files
 * automatically, so a fixture added later cannot quietly reintroduce one.
 *
 * Fixtures local to a `*.test.tsx` file are checked in that file, next to
 * where they are defined; this file covers everything Storybook collects.
 */

// The same story files `.storybook/main.ts` collects. Relative to this
// directory, so `../../**` is all of `src/`, new directories included.
// Written with braces: Vite's `import.meta.glob` silently matches nothing for
// the `@(a|b)` extglob form Storybook uses, so the filesystem cross-check
// below is what proves the glob still matches.
const storyModules = import.meta.glob<Record<string, unknown>>(
  '../../**/*.stories.{js,jsx,mjs,ts,tsx}',
  { eager: true },
)

// Vite rewrites `import.meta.url` under test, so resolve from Vitest's cwd
// (`apps/web`), as `src/test/storyA11yPolicy.test.ts` does.
const SRC_DIR = resolve(process.cwd(), 'src')
const HERE = resolve(SRC_DIR, 'components/EvidenceReceipts')

// Glob keys are relative to this file (`./X` in this directory, `../Y/X`
// elsewhere), so name every file by its path under `src/` instead.
const underSrc = (globKey: string) =>
  relative(SRC_DIR, resolve(HERE, globKey)).split(sep).join('/')

const rowsByFile: [string, CollectedGameRow[]][] = Object.entries(storyModules)
  .map(([file, storyModule]): [string, CollectedGameRow[]] => [
    underSrc(file),
    collectGameRows(storyModule, underSrc(file)),
  ])
  .sort(([a], [b]) => a.localeCompare(b))

const allRows = rowsByFile.flatMap(([, rows]) => rows)
const teamRelativeRows = allRows.filter((row) => row.kind === 'team-relative')

describe('story fixtures build only game rows the API could send (issue #294)', () => {
  it('walks every story file under src/', () => {
    const storyFilesOnDisk = readdirSync(SRC_DIR, {
      recursive: true,
      encoding: 'utf8',
    })
      .filter((path) => STORY_FILE_PATTERN.test(path))
      .map((path) => path.split(sep).join('/'))
      .sort()
    expect(storyFilesOnDisk.length).toBeGreaterThan(0)
    expect(
      Object.keys(storyModules).map(underSrc).sort(),
      'import.meta.glob must collect every story file under src/',
    ).toEqual(storyFilesOnDisk)
  })

  it('finds the game rows it is meant to check, with every venue represented', () => {
    // A fixture set that is uniformly one venue cannot catch a side-swap, and
    // a vacuous pass here would hide the whole check going quiet.
    expect(
      teamRelativeRows.length,
      'no team-relative game row found in any story fixture',
    ).toBeGreaterThan(0)
    for (const venue of VENUES) {
      expect(
        teamRelativeRows.filter((row) => row.venue === venue).length,
        `no story fixture builds a game row with venue ${venue}`,
      ).toBeGreaterThan(0)
    }
  })

  it.each(rowsByFile)('%s', (_file, rows) => {
    const problems = venueProblems(rows)
    expect(problems, problems.join('\n')).toEqual([])
  })
})
