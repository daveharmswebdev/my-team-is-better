import type { Meta, StoryObj } from '@storybook/react-vite'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { expect, within } from 'storybook/test'
import { AppShell } from './AppShell'

const meta = {
  title: 'components/AppShell',
  component: AppShell,
  tags: ['autodocs'],
  decorators: [
    (Story) => (
      <MemoryRouter initialEntries={['/']}>
        <Routes>
          <Route element={<Story />}>
            <Route
              path="/"
              element={
                <p style={{ padding: '2rem' }}>Page content goes here.</p>
              }
            />
          </Route>
        </Routes>
      </MemoryRouter>
    ),
  ],
} satisfies Meta<typeof AppShell>

export default meta

type Story = StoryObj<typeof meta>

/** The primary nav: the NFL leaders (issue #296) and How This Works. */
export const Default: Story = {
  play: async ({ canvasElement }) => {
    const nav = within(canvasElement).getByRole('navigation', {
      name: 'Primary',
    })
    await expect(
      within(nav).getByRole('link', { name: 'NFL Leaders' }),
    ).toHaveAttribute('href', '/nfl/leaders')
    await expect(
      within(nav).getByRole('link', { name: 'Compare Players' }),
    ).toHaveAttribute('href', '/nfl/compare')
    await expect(
      within(nav).getByRole('link', { name: 'How This Works' }),
    ).toHaveAttribute('href', '/about')
  },
}
