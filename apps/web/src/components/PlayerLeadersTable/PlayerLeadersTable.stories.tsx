import type { Meta, StoryObj } from '@storybook/react-vite'
import { MemoryRouter } from 'react-router-dom'
import { expect, fn, userEvent, within } from 'storybook/test'
import {
  LEADERS_BY_TDS,
  LEADERS_BY_YARDS,
  LEADERS_WITH_NULL_STATS,
} from '../../lib/playerFixtures'
import { PlayerLeadersTable } from './PlayerLeadersTable'

const meta = {
  title: 'components/PlayerLeadersTable',
  component: PlayerLeadersTable,
  tags: ['autodocs'],
  args: {
    leaders: LEADERS_BY_YARDS,
    onSort: fn(),
  },
  decorators: [
    (Story) => (
      <MemoryRouter>
        <Story />
      </MemoryRouter>
    ),
  ],
} satisfies Meta<typeof PlayerLeadersTable>

export default meta

type Story = StoryObj<typeof meta>

/** The committed fixture's regular-season top four by passing yards. */
export const ByPassingYards: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement)
    const header = canvas.getByRole('columnheader', { name: 'Passing yards' })
    await expect(header).toHaveAttribute('aria-sort', 'descending')
    await userEvent.click(canvas.getByRole('button', { name: 'Passing TDs' }))
    await expect(args.onSort).toHaveBeenCalledWith('passing_tds')
  },
}

/** A real tie: Dak Prescott and Steve Beuerlein share rank 2, as the API sends it. */
export const TiedRanks: Story = {
  args: { leaders: LEADERS_BY_TDS },
}

/** Stats the source didn't track read "not recorded", never 0 or blank. */
export const NullStats: Story = {
  args: { leaders: LEADERS_WITH_NULL_STATS },
}

/** The next page is on its way: the table stays, dimmed and `aria-busy`. */
export const Busy: Story = {
  args: { busy: true },
}
