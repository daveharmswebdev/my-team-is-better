import type { Meta, StoryObj } from '@storybook/react-vite'
import { MemoryRouter } from 'react-router-dom'
import { expect, within } from 'storybook/test'
import {
  ROUTE_ERROR_COPY,
  ROUTE_ERROR_HEADING,
  RouteErrorBoundary,
  type RouteErrorBoundaryProps,
} from './RouteErrorBoundary'

function ThrowingPage(): never {
  throw new Error('A page blew up while rendering (story fixture).')
}

const meta = {
  title: 'components/RouteErrorBoundary',
  component: RouteErrorBoundary,
  tags: ['autodocs'],
  args: {
    resetKey: 'story',
    children: <p style={{ padding: '2rem' }}>Page content goes here.</p>,
  },
  decorators: [
    (Story) => (
      <MemoryRouter initialEntries={['/nfl/leaders']}>
        <Story />
      </MemoryRouter>
    ),
  ],
  // Typed by props rather than `typeof RouteErrorBoundary`: Storybook's
  // component-class inference trips over the static
  // `getDerivedStateFromProps`.
} satisfies Meta<RouteErrorBoundaryProps>

export default meta

type Story = StoryObj<typeof meta>

/** Nothing threw: the boundary is invisible and renders the page as-is. */
export const NoError: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    await expect(canvas.getByText('Page content goes here.')).toBeVisible()
    await expect(canvas.queryByRole('alert')).toBeNull()
  },
}

/**
 * A page threw (issue #268): the narrator's fallback, announced as an alert,
 * with a link back to a working page and no raw error text.
 */
export const Fallback: Story = {
  args: { children: <ThrowingPage /> },
  play: async ({ canvasElement }) => {
    const alert = within(canvasElement).getByRole('alert')
    await expect(
      within(alert).getByRole('heading', { name: ROUTE_ERROR_HEADING }),
    ).toBeVisible()
    await expect(alert).toHaveTextContent(ROUTE_ERROR_COPY)
    await expect(alert).not.toHaveTextContent('blew up')
    await expect(
      within(alert).getByRole('link', { name: /back to the start/i }),
    ).toHaveAttribute('href', '/')
  },
}
