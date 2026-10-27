import js from '@eslint/js'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import storybook from 'eslint-plugin-storybook'
import eslintConfigPrettier from 'eslint-config-prettier'
import jsxA11y from 'eslint-plugin-jsx-a11y'
import globals from 'globals'
import tseslint from 'typescript-eslint'

/**
 * Lint layer of the Storybook a11y gate (issue #90; see
 * .storybook/a11yPolicy.ts). The run-time guard trusts a11y reports and story
 * state it reads in the same browser realm as story code, so these rules ban
 * the syntax that forges them.
 *
 * Everywhere in `src` except test files (`*.test.*`, `src/test/setup.ts`):
 * importing `vitest`, `@vitest/*`, `@storybook/addon-vitest` or `.storybook/*`,
 * statically or with `import()`.
 *
 * In story files (`src/**\/*.stories.*`) only:
 * - inside story annotation functions (`play`, `beforeEach`, `afterEach`,
 *   `loaders`, `decorators`, `render`, `mount`): reading or destructuring
 *   `reporting`, `a11y` or `ghostStories` (as `.key`, `['key']` or
 *   `` [`key`] ``), except on `args` / `props` and in `render`'s args
 *   parameter; assigning `parameters` / `globals`;
 * - anywhere in the file: assigning or deleting `viewMode`; the same reads
 *   and writes through a context-named identifier (`ctx`, `context`,
 *   `storyContext`) or through `parameters.` / `globals.`; and `Object` /
 *   `Reflect` mutators given `parameters` / `globals`, or a key
 *   `reporting` / `a11y` / `ghostStories` / `parameters` / `globals` /
 *   `viewMode`.
 * Declaring `parameters: { a11y: ... }` in an annotation object is untouched:
 * the policy test checks those values.
 *
 * Not covered (each is deliberate, and visible in review): keys computed at
 * run time (`ctx['rep' + 'orting']`, a key held in a variable); aliasing the
 * context under another name in a module-level helper outside an annotation
 * function (`function h(c) { c.reporting }` then `play: h`); `eval` / `new
 * Function`; code in test files or in `.storybook/**`; and `eslint-disable`
 * comments. `src/test/storyA11yPolicy.test.ts` proves these rules still
 * exist, fire on the forbidden forms, and stay quiet on ordinary code.
 */
const MESSAGE =
  'Story code must not forge a11y reports or change a11y settings at run time (issue #90, .storybook/a11yPolicy.ts). Declare parameters statically, or add a justified exemption.'

const oneOf = (alternatives) => `/^(${alternatives})$/`
const READ_KEYS = 'reporting|a11y|ghostStories'
const CONTEXT_OBJECT_KEYS = 'parameters|globals'
const ANY_KEYS = `${READ_KEYS}|${CONTEXT_OBJECT_KEYS}|viewMode`
const ANNOTATIONS = oneOf(
  'play|beforeEach|afterEach|loaders|decorators|render|mount',
)
const ARGS_OR_PROPS = oneOf('args|props')
const CONTEXT_NAMES = oneOf('ctx|context|storyContext')
const MUTATOR = `CallExpression[callee.object.name=${oneOf('Object|Reflect')}][callee.property.name=${oneOf('assign|defineProperty|defineProperties|set|deleteProperty|setPrototypeOf')}]`
const IN_ANNOTATION = `:matches(Property[key.name=${ANNOTATIONS}], AssignmentExpression[left.property.name=${ANNOTATIONS}])`

/** Attribute selectors for a key at `path` written `.k`, `['k']` or `` [`k`] ``. */
const keyForms = (path, computedAttr, keys) => [
  `[${path}.name=${oneOf(keys)}]`,
  `[${computedAttr}=true][${path}.value=${oneOf(keys)}]`,
  `[${computedAttr}=true][${path}.type='TemplateLiteral'][${path}.expressions.length=0][${path}.quasis.0.value.cooked=${oneOf(keys)}]`,
]
const memberKey = (keys) => keyForms('property', 'computed', keys)
const propertyKey = (keys) => keyForms('key', 'computed', keys)
const assignedKey = (keys) => keyForms('left.property', 'left.computed', keys)
const deletedKey = (keys) =>
  keyForms('argument.property', 'argument.computed', keys)

// Destructuring that reads args, not the story context.
const ARGS_DESTRUCTURING = `:matches(Property[key.name='render'] > :function > ObjectPattern:first-child > Property, Property[key.name=${ARGS_OR_PROPS}] > ObjectPattern > Property, VariableDeclarator[init.name=${ARGS_OR_PROPS}] > ObjectPattern > Property)`

const dynamicVitestImport = 'ImportExpression[source.value=/^@?vitest/]'

const storySyntax = [
  dynamicVitestImport,
  // inside story annotation functions
  ...memberKey(READ_KEYS).map(
    (key) =>
      `${IN_ANNOTATION} MemberExpression${key}:not([object.name=${ARGS_OR_PROPS}])`,
  ),
  ...propertyKey(READ_KEYS).map(
    (key) =>
      `${IN_ANNOTATION} ObjectPattern > Property${key}:not(${ARGS_DESTRUCTURING})`,
  ),
  ...assignedKey(CONTEXT_OBJECT_KEYS).map(
    (key) =>
      `${IN_ANNOTATION} AssignmentExpression${key}:not([left.object.name=${ARGS_OR_PROPS}])`,
  ),
  // anywhere in a story file
  ...assignedKey('viewMode').map((key) => `AssignmentExpression${key}`),
  ...deletedKey('viewMode').map(
    (key) => `UnaryExpression[operator='delete']${key}`,
  ),
  ...memberKey(READ_KEYS).map(
    (key) => `MemberExpression[object.name=${CONTEXT_NAMES}]${key}`,
  ),
  ...memberKey('a11y|ghostStories').flatMap((key) => [
    `MemberExpression[object.name=${oneOf(CONTEXT_OBJECT_KEYS)}]${key}`,
    `MemberExpression[object.property.name=${oneOf(CONTEXT_OBJECT_KEYS)}]${key}`,
  ]),
  ...assignedKey(CONTEXT_OBJECT_KEYS).map(
    (key) => `AssignmentExpression[left.object.name=${CONTEXT_NAMES}]${key}`,
  ),
  `${MUTATOR} > Identifier[name=${oneOf(CONTEXT_OBJECT_KEYS)}]`,
  ...memberKey(`${CONTEXT_OBJECT_KEYS}|a11y|ghostStories`).map(
    (key) => `${MUTATOR} > MemberExpression${key}`,
  ),
  ...propertyKey(ANY_KEYS).map(
    (key) => `${MUTATOR} > ObjectExpression > Property${key}`,
  ),
  `${MUTATOR} > Literal[value=${oneOf(ANY_KEYS)}]`,
  `${MUTATOR} > TemplateLiteral[expressions.length=0][quasis.0.value.cooked=${oneOf(ANY_KEYS)}]`,
].map((selector) => ({ selector, message: MESSAGE }))

/**
 * Issue #221: tests and stories fake the API one way, through the MSW
 * handlers in `src/mocks/handlers.ts`, so page and component tests run the
 * real `src/lib/api/client.ts` and no story leaks a fake `fetch` into the
 * next. Banned in every `src` file and in `.storybook/**`: assigning `fetch`
 * on `globalThis` / `window` / `self` / `global` (as `.fetch`, `['fetch']` or
 * `` [`fetch`] ``, any assignment operator), `Object.assign`-ing a `fetch`
 * onto one of them, `<x>.stubGlobal('fetch', ...)`, `<x>.spyOn(<global>,
 * 'fetch')`, and `vi.mock` / `vi.doMock` of the client module. A bare
 * `fetch = ...` on the global is core `no-global-assign`'s. Not covered:
 * computed keys built at run time, `globalThis` aliased through another
 * variable, `Object.defineProperty`, `eslint-disable`.
 * `src/test/eslintNetworkFakes.test.ts` proves each form is flagged in every
 * block that sets `no-restricted-syntax`, and ordinary code is not.
 */
const NETWORK_FAKE_MESSAGE =
  'Fake the API with MSW (src/mocks/handlers.ts: server.use() in a test, parameters.msw in a story), not by replacing fetch or mocking the API client (issue #221).'
const GLOBAL_OBJECTS = oneOf('globalThis|window|self|global')
const literalArg = (index, values) => [
  `[arguments.${index}.type='Literal'][arguments.${index}.value=${oneOf(values)}]`,
  `[arguments.${index}.type='TemplateLiteral'][arguments.${index}.expressions.length=0][arguments.${index}.quasis.0.value.cooked=${oneOf(values)}]`,
]
const CLIENT_MODULE = '/(^|\\/)(lib\\/api\\/)?client(\\.ts)?$/'
const VI_MOCK = `CallExpression[callee.object.name='vi'][callee.property.name=${oneOf('mock|doMock')}]`

const networkFakeSyntax = [
  ...assignedKey('fetch').map(
    (key) => `AssignmentExpression[left.object.name=${GLOBAL_OBJECTS}]${key}`,
  ),
  ...propertyKey('fetch').map(
    (key) =>
      `CallExpression[callee.object.name='Object'][callee.property.name='assign'][arguments.0.name=${GLOBAL_OBJECTS}] > ObjectExpression > Property${key}`,
  ),
  ...literalArg(0, 'fetch').map(
    (arg) => `CallExpression[callee.property.name='stubGlobal']${arg}`,
  ),
  ...literalArg(1, 'fetch').map(
    (arg) =>
      `CallExpression[callee.property.name='spyOn'][arguments.0.name=${GLOBAL_OBJECTS}]${arg}`,
  ),
  `${VI_MOCK}[arguments.0.type='Literal'][arguments.0.value=${CLIENT_MODULE}]`,
  `${VI_MOCK}[arguments.0.type='ImportExpression'][arguments.0.source.value=${CLIENT_MODULE}]`,
].map((selector) => ({ selector, message: NETWORK_FAKE_MESSAGE }))

export default tseslint.config(
  { ignores: ['dist', 'storybook-static', 'coverage'] },
  {
    extends: [
      js.configs.recommended,
      ...tseslint.configs.recommendedTypeChecked,
      reactHooks.configs.flat['recommended-latest'],
      reactRefresh.configs.vite,
    ],
    files: ['**/*.{ts,tsx}'],
    languageOptions: {
      ecmaVersion: 2023,
      globals: globals.browser,
      // Issue #222: type-aware rules (floating promises, `any` leaking out
      // of untyped values, ...). The project service finds each file's
      // tsconfig through the solution `tsconfig.json`'s references.
      parserOptions: {
        projectService: true,
        tsconfigRootDir: import.meta.dirname,
      },
    },
  },
  {
    // Issue #222: three type-aware rules that reject canonical React Testing
    // Library / Vitest idioms, off in test files only (story and source files
    // keep the full set; src/test/eslintTypeAware.test.ts checks both sides).
    name: 'type-aware/test-files',
    files: ['**/*.test.{ts,tsx}', 'src/test/setup.ts'],
    rules: {
      // `await act(async () => { sync() })` is RTL's documented way to flush
      // the updates a resolved promise schedules, and `async it()` with no
      // await is ordinary test style.
      '@typescript-eslint/require-await': 'off',
      // Asymmetric matchers (`expect.any`, `expect.stringMatching`, ...) are
      // typed `any` by Vitest, so every `toEqual({ a: expect.any(String) })`
      // would be flagged.
      '@typescript-eslint/no-unsafe-assignment': 'off',
      // `expect(obj.method).toHaveBeenCalled()` passes a method without
      // calling it; Vitest's own guidance is to turn this rule off in tests.
      '@typescript-eslint/unbound-method': 'off',
    },
  },
  {
    // Issue #222: static accessibility checks on JSX (a click handler on a
    // <div> with no key handler or role, a missing alt, ...). The storybook
    // a11y addon checks rendered stories at run time; this catches the same
    // mistakes in code no story renders. eslint-plugin-jsx-a11y 6.10.2 lists
    // `eslint` up to ^9 as a peer; package.json's `overrides` points that
    // peer at our ESLint 10 (the plugin uses none of the context APIs 10
    // removed), and src/test/eslintTypeAware.test.ts proves its rules fire.
    ...jsxA11y.flatConfigs.recommended,
    name: 'jsx-a11y/recommended',
    files: ['**/*.{jsx,tsx}'],
  },
  ...storybook.configs['flat/recommended'],
  {
    name: 'a11y-gate/imports',
    files: ['src/**/*.{js,jsx,mjs,ts,tsx}'],
    ignores: ['src/**/*.test.{js,jsx,mjs,ts,tsx}', 'src/test/setup.ts'],
    rules: {
      'no-restricted-imports': [
        'error',
        {
          patterns: [
            {
              group: [
                'vitest',
                'vitest/**',
                '@vitest/**',
                '@storybook/addon-vitest',
                '@storybook/addon-vitest/**',
                '**/.storybook',
                '**/.storybook/**',
              ],
              message: MESSAGE,
            },
          ],
        },
      ],
      'no-restricted-syntax': [
        'error',
        { selector: dynamicVitestImport, message: MESSAGE },
        ...networkFakeSyntax,
      ],
    },
  },
  {
    // Issue #221. The blocks above and below set `no-restricted-syntax` for
    // source and story files, and a later block's list replaces an earlier
    // one's, so each carries `networkFakeSyntax` itself.
    name: 'network-fakes/test-and-storybook-files',
    files: [
      'src/**/*.test.{js,jsx,mjs,ts,tsx}',
      'src/test/setup.ts',
      '.storybook/**/*.{js,jsx,mjs,ts,tsx}',
    ],
    rules: {
      'no-restricted-syntax': ['error', ...networkFakeSyntax],
    },
  },
  {
    name: 'a11y-gate/story-files',
    files: ['src/**/*.stories.{js,jsx,mjs,ts,tsx}'],
    rules: {
      'no-restricted-syntax': ['error', ...storySyntax, ...networkFakeSyntax],
    },
  },
  {
    // `preview.tsx`, `*.setup.ts` and `a11yPolicy.ts` (imported by the guard)
    // run in the browser. tsconfig.storybook.json gives the first two DOM +
    // JSX, but dependency type declarations still pull @types/node into that
    // program, so `tsc` cannot reject Node globals here.
    name: 'storybook/browser-side-files',
    files: [
      '.storybook/*.tsx',
      '.storybook/*.setup.ts',
      '.storybook/a11yPolicy.ts',
    ],
    rules: {
      'no-restricted-globals': [
        'error',
        ...[
          'process',
          'Buffer',
          'require',
          '__dirname',
          '__filename',
          'global',
        ].map((name) => ({
          name,
          message:
            'Browser-side Storybook file: Node globals do not exist at run time.',
        })),
      ],
    },
  },
  {
    // Issue #242: every e2e spec runs under `e2e/fixtures.ts`'s `test`, which
    // answers third-party requests itself so no page load waits on the
    // internet. Importing Playwright's own `test` would skip that silently.
    // Both specifiers export the same `test`, named and as the default
    // export, and the files glob covers every extension Playwright's default
    // `testMatch` picks up. The TypeScript parser is set here because the
    // shared `**/*.{ts,tsx}` block doesn't match `.mts` / `.cts`, which would
    // otherwise go unlinted ("no matching configuration").
    name: 'e2e/harness-test',
    files: ['e2e/**/*.{ts,tsx,mts,cts,js,jsx,mjs,cjs}'],
    ignores: ['e2e/fixtures.ts'],
    languageOptions: { parser: tseslint.parser },
    rules: {
      'no-restricted-imports': [
        'error',
        {
          paths: ['@playwright/test', 'playwright/test'].map((name) => ({
            name,
            importNames: ['test', 'default'],
            message:
              "Import `test` from './fixtures.ts': it keeps e2e page loads off the internet (issue #242).",
          })),
        },
      ],
    },
  },
  eslintConfigPrettier,
)
