import type { Meta, StoryObj } from '@storybook/react-vite'
import { expect, within } from 'storybook/test'
import {
  DEFENSE_EARLY_ERA_NOTE,
  DEFENSE_UNOFFICIAL_NOTE,
} from '../../lib/playerStats'
import { LeaderColumnNotes } from './LeaderColumnNotes'

const meta = {
  title: 'components/LeaderColumnNotes',
  component: LeaderColumnNotes,
  tags: ['autodocs'],
  args: { category: 'defense', idPrefix: 'story-notes' },
} satisfies Meta<typeof LeaderColumnNotes>

export default meta

type Story = StoryObj<typeof meta>

/** The defense board's two notes (#316, issue #317), each led by its headers' marker. */
export const Defense: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    await expect(canvas.getByText(DEFENSE_EARLY_ERA_NOTE)).toHaveAttribute(
      'id',
      'story-notes-early-era',
    )
    await expect(canvas.getByText(DEFENSE_UNOFFICIAL_NOTE)).toHaveAttribute(
      'id',
      'story-notes-unofficial',
    )
  },
}

/** A board whose columns need no note: nothing renders. */
export const Kicking: Story = {
  args: { category: 'kicking' },
  play: async ({ canvasElement }) => {
    await expect(
      within(canvasElement).queryByText(DEFENSE_EARLY_ERA_NOTE),
    ).not.toBeInTheDocument()
  },
}
