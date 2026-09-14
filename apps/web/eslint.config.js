import js from '@eslint/js'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import storybook from 'eslint-plugin-storybook'
import eslintConfigPrettier from 'eslint-config-prettier'
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

export default tseslint.config(
  { ignores: ['dist', 'storybook-static', 'coverage'] },
  {
    extends: [
      js.configs.recommended,
      ...tseslint.configs.recommended,
      reactHooks.configs.flat['recommended-latest'],
      reactRefresh.configs.vite,
    ],
    files: ['**/*.{ts,tsx}'],
    languageOptions: {
      ecmaVersion: 2023,
      globals: globals.browser,
    },
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
      ],
    },
  },
  {
    name: 'a11y-gate/story-files',
    files: ['src/**/*.stories.{js,jsx,mjs,ts,tsx}'],
    rules: {
      'no-restricted-syntax': ['error', ...storySyntax],
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
  eslintConfigPrettier,
)
