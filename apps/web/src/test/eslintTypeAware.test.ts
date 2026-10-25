import { ESLint } from 'eslint'
import { describe, expect, it } from 'vitest'

/**
 * Issue #222: `eslint.config.js` lints TypeScript with type information
 * (`tseslint.configs.recommendedTypeChecked` plus `projectService`) and lints
 * JSX against `eslint-plugin-jsx-a11y`'s recommended rules. This runs the real
 * config through ESLint's Node API, as `storyA11yPolicy.test.ts` does, so a
 * config edit that drops either layer (or turns its rules down to warnings)
 * fails `npm run test`, and so does one that starts flagging ordinary code.
 *
 * Each probe is linted under the path of a real source file: the project
 * service only types files its tsconfig already lists on disk (a made-up
 * path is a parse error), and the text given to `lintText` stands in for
 * that file's contents. Nothing is written to disk. A parse error fails both
 * halves (no expected rule fires; the clean probe isn't clean), so a moved
 * probe file can't make this pass vacuously.
 */

// Vitest's cwd is `apps/web` (see `storyA11yPolicy.test.ts`).
const WEB_DIR = process.cwd()
const PROBE_TS = 'src/lib/formatRating.ts'
const PROBE_TSX = 'src/components/ShareButton/ShareButton.tsx'
const PROBE_TEST_TSX = 'src/components/ShareButton/ShareButton.test.tsx'

const show = (value: unknown) => JSON.stringify(value, null, 2)

/** [description, probe path, code, rules of which at least one must error] */
const FORBIDDEN: [string, string, string, string[]][] = [
  [
    'a floating promise',
    PROBE_TS,
    'async function load(): Promise<number> {\n  return Promise.resolve(1)\n}\n\nexport function start(): void {\n  load()\n}\n',
    ['@typescript-eslint/no-floating-promises'],
  ],
  [
    'an unsafe assignment from an `any`',
    PROBE_TS,
    'export function parse(text: string): string {\n  const value = JSON.parse(text)\n  return String(value)\n}\n',
    ['@typescript-eslint/no-unsafe-assignment'],
  ],
  [
    'a <div onClick> with no key handler',
    PROBE_TSX,
    'export function Clicky({ onPick }: { onPick: () => void }) {\n  return <div onClick={onPick}>pick</div>\n}\n',
    [
      'jsx-a11y/click-events-have-key-events',
      'jsx-a11y/no-static-element-interactions',
    ],
  ],
]

/** [description, probe path, code]: must produce no errors at all. */
const ORDINARY: [string, string, string][] = [
  [
    'an awaited promise',
    PROBE_TS,
    'async function load(): Promise<number> {\n  return Promise.resolve(1)\n}\n\nexport async function start(): Promise<number> {\n  const value = await load()\n  return value + 1\n}\n',
  ],
  [
    'a <button onClick>',
    PROBE_TSX,
    'export function Picker({ onPick }: { onPick: () => void }) {\n  return (\n    <button type="button" onClick={onPick}>\n      pick\n    </button>\n  )\n}\n',
  ],
]

/**
 * Canonical React Testing Library / Vitest idioms the type-aware rules reject
 * (issue #222 round 2). The test-file override turns exactly these rules off,
 * so each probe must lint clean under a test path and still error under a
 * source path: the override can't silently widen to shipped code.
 * [description, code, rule it trips outside test files]
 */
const TEST_IDIOMS: [string, string, string][] = [
  [
    '`await act(async () => { sync() })`',
    "import { act } from '@testing-library/react'\nimport { it } from 'vitest'\n\nconst sync = (): void => undefined\n\nit('acts', async () => {\n  await act(async () => {\n    sync()\n  })\n})\n",
    '@typescript-eslint/require-await',
  ],
  [
    'an `async it()` with no await',
    "import { expect, it } from 'vitest'\n\nit('checks', async () => {\n  expect(1).toBe(1)\n})\n",
    '@typescript-eslint/require-await',
  ],
  [
    '`toEqual({ a: expect.any(String) })`',
    "import { expect, it } from 'vitest'\n\nit('matches', () => {\n  expect({ a: 'b' }).toEqual({ a: expect.any(String) })\n})\n",
    '@typescript-eslint/no-unsafe-assignment',
  ],
  [
    '`expect(obj.m).toHaveBeenCalled()`',
    "import { expect, it, vi } from 'vitest'\n\ninterface Thing {\n  m(): void\n}\n\nit('spies', () => {\n  const obj: Thing = { m: vi.fn() }\n  obj.m()\n  expect(obj.m).toHaveBeenCalled()\n})\n",
    '@typescript-eslint/unbound-method',
  ],
]

describe('eslint.config.js type-aware and jsx-a11y layers (issue #222)', () => {
  const eslint = new ESLint({ cwd: WEB_DIR })

  it.each(FORBIDDEN)(
    'rejects %s',
    async (_description, filePath, code, rules) => {
      const [result] = await eslint.lintText(code, { filePath })
      const messages = result?.messages ?? []
      const hits = messages.filter(
        (message) =>
          message.severity === 2 && rules.includes(message.ruleId ?? ''),
      )
      expect(
        hits.length,
        `no error from ${rules.join(' / ')} for:\n${code}\nmessages: ${show(messages)}`,
      ).toBeGreaterThan(0)
    },
  )

  it.each(ORDINARY)(
    'leaves ordinary code alone: %s',
    async (_description, filePath, code) => {
      const [result] = await eslint.lintText(code, { filePath })
      expect(
        result?.messages ?? [],
        `false positive in ${filePath}:\n${code}`,
      ).toEqual([])
    },
  )

  it.each(TEST_IDIOMS)(
    'accepts %s in a test file',
    async (_description, code) => {
      const [result] = await eslint.lintText(code, {
        filePath: PROBE_TEST_TSX,
      })
      expect(
        result?.messages ?? [],
        `false positive in ${PROBE_TEST_TSX}:\n${code}`,
      ).toEqual([])
    },
  )

  it.each(TEST_IDIOMS)(
    'still rejects %s outside test files',
    async (_description, code, rule) => {
      const [result] = await eslint.lintText(code, { filePath: PROBE_TS })
      const messages = result?.messages ?? []
      const hits = messages.filter(
        (message) => message.severity === 2 && message.ruleId === rule,
      )
      expect(
        hits.length,
        `no ${rule} error in ${PROBE_TS} for:\n${code}\nmessages: ${show(messages)}`,
      ).toBeGreaterThan(0)
    },
  )
})
