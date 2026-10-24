import type { StorybookConfig } from '@storybook/react-vite'

const config: StorybookConfig = {
  stories: ['../src/**/*.mdx', '../src/**/*.stories.@(js|jsx|mjs|ts|tsx)'],
  addons: [
    '@storybook/addon-a11y',
    '@storybook/addon-docs',
    '@storybook/addon-vitest',
  ],
  framework: '@storybook/react-vite',
  // Serves public/ at the root, as the app does, so src/styles/fonts.css's
  // /fonts/*.woff2 urls resolve in Storybook too (issue #408).
  staticDirs: ['../public'],
}
export default config
