import js from '@eslint/js'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import storybook from 'eslint-plugin-storybook'
import eslintConfigPrettier from 'eslint-config-prettier'
import globals from 'globals'
import tseslint from 'typescript-eslint'

/**
 * Lint layer of the Storybook a11y gate (issue #90; see
 * .storybook/a11yPolicy.ts). The run-time guard trusts the a11y report and
 * story state it reads in the same browser realm as story code, so this rule
 * bans the syntax that forges that report or changes a11y settings at run
 * time, everywhere in `src` except unit tests:
 * - importing `vitest` / `@vitest/*` / addon-vitest (statically or with
 *   `import()`), which gives access to test hooks and `task.meta`;
 * - reading `reporting` from a story context (`addReport` forgery);
 * - any `.a11y` / `.ghostStories` member access or destructuring (every way
 *   to mutate or alias `parameters.a11y`, `globals.a11y`,
 *   `globals.ghostStories` starts there), reassigning `.parameters` /
 *   `.globals`, and `Object` / `Reflect` mutators aimed at them.
 * Declaring `parameters: { a11y: ... }` in an annotation object is untouched:
 * the policy test checks those values.
 *
 * Still possible, but only deliberately: computed keys built at run time
 * (`parameters[key]`), `eval` / `Function`, mutation from a `*.test.*` file or
 * from `.storybook/**`, or an `eslint-disable` comment -- each leaves a
 * visible trace in the diff. `src/test/storyA11yPolicy.test.ts` proves the
 * rule still exists and fires.
 */
const A11Y_KEYS = '/^(a11y|ghostStories)$/'
const CONTEXT_KEYS = '/^(parameters|globals)$/'
const MUTATORS =
  '/^(assign|defineProperty|defineProperties|set|deleteProperty|setPrototypeOf)$/'
const A11Y_GATE_MESSAGE =
  'Story/app code must not forge a11y reports or change a11y settings at run time (issue #90, .storybook/a11yPolicy.ts). Declare parameters statically, or add a justified exemption.'

const a11yGateSyntax = [
  // vitest access by dynamic import (static imports: no-restricted-imports)
  'ImportExpression[source.value=/^@?vitest/]',
  // addReport forgery
  "MemberExpression[property.name='reporting']",
  "MemberExpression[computed=true][property.value='reporting']",
  "ObjectPattern > Property[key.name='reporting']",
  "ObjectPattern > Property[key.value='reporting']",
  // a11y settings: any access, alias or destructuring
  `MemberExpression[property.name=${A11Y_KEYS}]`,
  `MemberExpression[computed=true][property.value=${A11Y_KEYS}]`,
  `ObjectPattern > Property[key.name=${A11Y_KEYS}]`,
  `ObjectPattern > Property[key.value=${A11Y_KEYS}]`,
  // replacing the whole parameters / globals object
  `AssignmentExpression[left.property.name=${CONTEXT_KEYS}]`,
  // Object.assign(parameters, { a11y }), Object.assign(ctx.globals, ...)
  `CallExpression[callee.object.name=/^(Object|Reflect)$/][callee.property.name=${MUTATORS}] > Identifier[name=${CONTEXT_KEYS}]`,
  `CallExpression[callee.object.name=/^(Object|Reflect)$/][callee.property.name=${MUTATORS}] > MemberExpression[property.name=${CONTEXT_KEYS}]`,
  `CallExpression[callee.object.name=/^(Object|Reflect)$/][callee.property.name=${MUTATORS}] Property[key.name=${A11Y_KEYS}]`,
  `CallExpression[callee.object.name='Reflect'] > Literal[value=${A11Y_KEYS}]`,
].map((selector) => ({ selector, message: A11Y_GATE_MESSAGE }))

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
    name: 'a11y-gate/story-and-app-code',
    files: ['src/**/*.{js,jsx,mjs,ts,tsx}'],
    ignores: ['src/**/*.test.{js,jsx,mjs,ts,tsx}', 'src/test/**'],
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
              ],
              message: A11Y_GATE_MESSAGE,
            },
          ],
        },
      ],
      'no-restricted-syntax': ['error', ...a11yGateSyntax],
    },
  },
  {
    // `preview.tsx` and `*.setup.ts` run in the browser. tsconfig.storybook.json
    // gives them DOM + JSX, but dependency type declarations still pull
    // @types/node into that program, so `tsc` cannot reject Node globals here.
    name: 'storybook/browser-side-files',
    files: ['.storybook/*.tsx', '.storybook/*.setup.ts'],
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
