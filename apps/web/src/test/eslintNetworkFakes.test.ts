import { ESLint } from 'eslint'
import { describe, expect, it } from 'vitest'

/**
 * Issue #221: tests and stories fake the API one way, with the MSW handlers
 * in `src/mocks/handlers.ts` (`server.use()` in a test, `parameters.msw` in a
 * story), so every page and component test exercises the real
 * `src/lib/api/client.ts`. `eslint.config.js` bans the patterns that faked it
 * before: replacing the global `fetch` (assigning it, `vi.stubGlobal`,
 * `vi.spyOn`, `Object.assign`) and `vi.mock`-ing the client module.
 *
 * Like `eslintTypeAware.test.ts`, this runs the real config through ESLint's
 * Node API. Each probe is linted under the path of a real file in each
 * config block that sets `no-restricted-syntax` (source, story, test, test
 * setup, `.storybook`), so a block that overrides the rule without the
 * network-fake selectors fails here. Ordinary probes must lint with no
 * messages at all, so a probe that stops parsing fails both halves.
 *
 * Not covered (deliberate evasion, visible in review): computed keys built
 * at run time, `globalThis` aliased through another variable,
 * `Object.defineProperty`, and `eslint-disable` comments.
 */

// Vitest's cwd is `apps/web` (see `storyA11yPolicy.test.ts`).
const WEB_DIR = process.cwd()

const PROBES = {
  source: 'src/lib/formatRating.ts',
  story: 'src/pages/AboutPage/AboutPage.stories.tsx',
  test: 'src/pages/AboutPage/AboutPage.test.tsx',
  setup: 'src/test/setup.ts',
  storybook: '.storybook/preview.tsx',
} as const

type ProbeKind = keyof typeof PROBES

const ALL_KINDS = Object.keys(PROBES) as ProbeKind[]
const TEST_KINDS: ProbeKind[] = ['test', 'setup']

/** The rules a network fake must trip, at least one of them, as an error. */
const NETWORK_FAKE_RULES = ['no-restricted-syntax', 'no-global-assign']

const show = (value: unknown) => JSON.stringify(value, null, 2)

/** [description, code, kinds of file it must be rejected in] */
const FORBIDDEN: [string, string, ProbeKind[]][] = [
  [
    '`globalThis.fetch = ...`',
    'globalThis.fetch = () => Promise.resolve(new Response(null))\n',
    ALL_KINDS,
  ],
  [
    '`window.fetch = ...`',
    'window.fetch = () => Promise.resolve(new Response(null))\n',
    ALL_KINDS,
  ],
  [
    "`globalThis['fetch'] = ...`",
    "globalThis['fetch'] = () => Promise.resolve(new Response(null))\n",
    ALL_KINDS,
  ],
  [
    '`self.fetch ??= ...`',
    'self.fetch ??= () => Promise.resolve(new Response(null))\n',
    ALL_KINDS,
  ],
  [
    'a bare `fetch = ...` on the global',
    'fetch = () => Promise.resolve(new Response(null))\n',
    ALL_KINDS,
  ],
  [
    "`vi.stubGlobal('fetch', ...)`",
    "import { vi } from 'vitest'\n\nvi.stubGlobal('fetch', vi.fn())\n",
    TEST_KINDS,
  ],
  [
    '`vi.stubGlobal(`fetch`, ...)`',
    "import { vi } from 'vitest'\n\nvi.stubGlobal(`fetch`, vi.fn())\n",
    TEST_KINDS,
  ],
  [
    "`vi.spyOn(globalThis, 'fetch')`",
    "import { vi } from 'vitest'\n\nvi.spyOn(globalThis, 'fetch')\n",
    TEST_KINDS,
  ],
  [
    "`vi.spyOn(window, 'fetch')`",
    "import { vi } from 'vitest'\n\nvi.spyOn(window, 'fetch')\n",
    TEST_KINDS,
  ],
  [
    '`Object.assign(globalThis, { fetch })`',
    'const fetch = () => Promise.resolve(new Response(null))\nObject.assign(globalThis, { fetch })\n',
    ALL_KINDS,
  ],
  [
    "`vi.mock('../../lib/api/client')`",
    "import { vi } from 'vitest'\n\nvi.mock('../../lib/api/client')\n",
    TEST_KINDS,
  ],
  [
    "`vi.mock('../../lib/api/client', factory)`",
    "import { vi } from 'vitest'\n\nvi.mock('../../lib/api/client', () => ({}))\n",
    TEST_KINDS,
  ],
  [
    "`vi.doMock('./client')`",
    "import { vi } from 'vitest'\n\nvi.doMock('./client')\n",
    TEST_KINDS,
  ],
  [
    "`vi.mock(import('../../lib/api/client'))`",
    "import { vi } from 'vitest'\n\nvi.mock(import('../../lib/api/client'))\n",
    TEST_KINDS,
  ],
]

/** [description, code, kinds of file it must lint clean in] */
const ORDINARY: [string, string, ProbeKind[]][] = [
  [
    'a local variable named `fetch`, reassigned',
    "export function pick(flag: boolean): string {\n  let fetch = 'a'\n  if (flag) {\n    fetch = 'b'\n  }\n  return fetch\n}\n",
    ['source', 'story', 'test'],
  ],
  [
    'a call to `fetch()`',
    "export async function load(): Promise<number> {\n  const response = await fetch('/api/years')\n  return response.status\n}\n",
    ['source', 'story', 'test'],
  ],
  [
    'a call to `window.fetch()`, and reading `globalThis.fetch`',
    "export async function load(): Promise<number> {\n  const real = globalThis.fetch\n  const response = await window.fetch('/api/years')\n  return response.status + real.length\n}\n",
    ['source', 'story', 'test'],
  ],
  [
    'a `fetch` property on an ordinary object',
    "interface Loader {\n  fetch: () => string\n}\n\nexport function rewire(loader: Loader): Loader {\n  loader.fetch = () => 'x'\n  return loader\n}\n",
    ['source', 'story', 'test'],
  ],
  [
    "`vi.stubGlobal('matchMedia', ...)` and `vi.spyOn(console, 'error')`",
    "import { it, vi } from 'vitest'\n\nit('stubs', () => {\n  vi.stubGlobal('matchMedia', vi.fn())\n  vi.spyOn(console, 'error').mockImplementation(() => {})\n})\n",
    TEST_KINDS,
  ],
  [
    '`vi.mock` of a page module',
    "import { vi } from 'vitest'\n\nvi.mock('./pages/HomePage/HomePage')\n",
    ['test'],
  ],
]

/** Story files must default-export a meta (`storybook/default-exports`). */
const STORY_META = "\nexport default { title: 'Probe' }\n"

const cases = <T extends [string, string, ProbeKind[]]>(rows: T[]) =>
  rows.flatMap(([description, code, kinds]) =>
    kinds.map(
      (kind) =>
        [
          description,
          kind,
          PROBES[kind],
          kind === 'story' ? `${code}${STORY_META}` : code,
        ] as const,
    ),
  )

// The first lint starts the TypeScript project service (see
// `eslintTypeAware.test.ts`), so this suite gets its own timeout.
describe(
  'eslint.config.js bans faking the network outside MSW (issue #221)',
  { timeout: 30_000 },
  () => {
    const eslint = new ESLint({ cwd: WEB_DIR })

    it.each(cases(FORBIDDEN))(
      'rejects %s in a %s file',
      async (_description, _kind, filePath, code) => {
        const [result] = await eslint.lintText(code, { filePath })
        const messages = result?.messages ?? []
        const hits = messages.filter(
          (message) =>
            message.severity === 2 &&
            NETWORK_FAKE_RULES.includes(message.ruleId ?? ''),
        )
        expect(
          hits.length,
          `no error from ${NETWORK_FAKE_RULES.join(' / ')} in ${filePath} for:\n${code}\nmessages: ${show(messages)}`,
        ).toBeGreaterThan(0)
      },
    )

    it.each(cases(ORDINARY))(
      'leaves %s alone in a %s file',
      async (_description, _kind, filePath, code) => {
        const [result] = await eslint.lintText(code, { filePath })
        expect(
          result?.messages ?? [],
          `false positive in ${filePath}:\n${code}`,
        ).toEqual([])
      },
    )
  },
)
