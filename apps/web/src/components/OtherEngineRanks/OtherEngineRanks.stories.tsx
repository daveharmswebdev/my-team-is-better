import type { Meta, StoryObj } from '@storybook/react-vite'
import { expect, fn, userEvent, within } from 'storybook/test'
import { OtherEngineRanks } from './OtherEngineRanks'

/**
 * Issue #155: where the other engines the Engine toggle offers rank the
 * verdict's team, in the quiet register of the card's "Engine: ..." line.
 */
const meta = {
  title: 'components/OtherEngineRanks',
  component: OtherEngineRanks,
  tags: ['autodocs'],
  args: {
    onSelectMethod: fn(),
  },
} satisfies Meta<typeof OtherEngineRanks>

export default meta

type Story = StoryObj<typeof meta>

/** A Keener team case: Elo's rank, plus a control to ask Elo. `elo_career` is never shown. */
export const TeamCase: Story = {
  args: {
    rows: [
      {
        ranks: [
          { method: 'elo', rank: 6 },
          { method: 'elo_career', rank: 8 },
        ],
      },
    ],
  },
  play: async ({ args, canvasElement }) => {
    const canvas = within(canvasElement)
    await expect(canvas.getByText('Elo (second opinion): #6')).toBeVisible()
    await userEvent.click(
      canvas.getByRole('button', { name: 'Ask Elo (second opinion)' }),
    )
    await expect(args.onSelectMethod).toHaveBeenCalledWith('elo')
  },
}

/** An Elo team case: Keener's rank, plus a control to ask Keener. */
export const TeamCaseAnsweredByElo: Story = {
  args: {
    rows: [{ ranks: [{ method: 'keener', rank: 3 }] }],
  },
}

/** A compare verdict: a line for each team, and one control for the whole question. */
export const Comparison: Story = {
  args: {
    rows: [
      { teamName: 'Penn State', ranks: [{ method: 'elo', rank: 6 }] },
      { teamName: 'Texas', ranks: [{ method: 'elo', rank: 1 }] },
    ],
  },
}

/** No handler: the ranks with no control. */
export const WithoutControl: Story = {
  args: {
    rows: [{ ranks: [{ method: 'elo', rank: 6 }] }],
    onSelectMethod: undefined,
  },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).queryByRole('button')).toBeNull()
  },
}
