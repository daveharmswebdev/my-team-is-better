import type { Meta, StoryObj } from '@storybook/react-vite'
import { expect, userEvent, within } from 'storybook/test'
import { EPA_EXPLANATION } from '../../lib/playerStats'
import { EpaExplanation } from './EpaExplanation'

const meta = {
  title: 'components/EpaExplanation',
  component: EpaExplanation,
  tags: ['autodocs'],
} satisfies Meta<typeof EpaExplanation>

export default meta

type Story = StoryObj<typeof meta>

/** Closed, as a page first shows it (#347): one named button. */
export const Closed: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    await expect(
      canvas.getByRole('button', { name: 'What is EPA?' }),
    ).toHaveAttribute('aria-expanded', 'false')
  },
}

/** Open: what EPA is, and how EPA per dropback and per carry are computed. */
export const Open: Story = {
  args: { defaultOpen: true },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    await expect(
      canvas.getByRole('region', { name: 'What is EPA?' }),
    ).toHaveTextContent(EPA_EXPLANATION)
  },
}

/** Opened from the keyboard. */
export const OpenedByKeyboard: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    const button = canvas.getByRole('button', { name: 'What is EPA?' })
    button.focus()
    await userEvent.keyboard('{Enter}')
    await expect(button).toHaveAttribute('aria-expanded', 'true')
    await expect(canvas.getByText(EPA_EXPLANATION)).toBeVisible()
  },
}
