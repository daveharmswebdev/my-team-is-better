import type { Meta, StoryObj } from '@storybook/react-vite'
import { MemoryRouter } from 'react-router-dom'
import { expect, fn, userEvent, within } from 'storybook/test'
import {
  DEFENSE_WITH_NULL_STATS,
  LEADERS_BY_DEF_SACKS,
  LEADERS_BY_DEF_SACKS_TAIL,
  LEADERS_BY_FG_MADE,
  LEADERS_BY_FG_MADE_TAIL,
  LEADERS_BY_FG_PCT,
  LEADERS_BY_PT_YARDS,
  LEADERS_BY_RECEIVING_TDS,
  LEADERS_BY_RECEIVING_YARDS,
  LEADERS_BY_RECEPTIONS_TAIL,
  LEADERS_BY_RUSHING_TDS,
  LEADERS_BY_RUSHING_YARDS,
  LEADERS_BY_TDS,
  LEADERS_BY_YARDS,
  LEADERS_WITH_NULL_STATS,
} from '../../lib/playerFixtures'
import {
  DEFENSE_EARLY_ERA_NOTE,
  DEFENSE_UNOFFICIAL_NOTE,
} from '../../lib/playerStats'
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

/**
 * The rushing board (issue #312): its own three sortable columns, no starter
 * record and no passing stats.
 */
export const ByRushingYards: Story = {
  args: { leaders: LEADERS_BY_RUSHING_YARDS },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement)
    await expect(
      canvas.getByRole('columnheader', { name: 'Rushing yards' }),
    ).toHaveAttribute('aria-sort', 'descending')
    await expect(
      canvas.queryByRole('columnheader', { name: 'Starter record' }),
    ).toBeNull()
    await userEvent.click(canvas.getByRole('button', { name: 'Carries' }))
    await expect(args.onSort).toHaveBeenCalledWith('carries')
  },
}

/** Two quarterbacks tied at rank 3 on the rushing board, each with a position. */
export const ByRushingTds: Story = {
  args: { leaders: LEADERS_BY_RUSHING_TDS },
}

/**
 * The receiving board (issue #314): receptions, receiving yards and TDs, all
 * sortable, with no starter record, no passing or rushing stats, and no
 * targets (#345).
 */
export const ByReceivingYards: Story = {
  args: { leaders: LEADERS_BY_RECEIVING_YARDS },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement)
    await expect(
      canvas.getByRole('columnheader', { name: 'Receiving yards' }),
    ).toHaveAttribute('aria-sort', 'descending')
    await expect(
      canvas.queryByRole('columnheader', { name: 'Starter record' }),
    ).toBeNull()
    await expect(
      canvas.queryByRole('columnheader', { name: 'Carries' }),
    ).toBeNull()
    await userEvent.click(canvas.getByRole('button', { name: 'Receptions' }))
    await expect(args.onSort).toHaveBeenCalledWith('receptions')
  },
}

/** A three-way tie at rank 1 by receiving TDs, as the API sends it. */
export const ByReceivingTds: Story = {
  args: { leaders: LEADERS_BY_RECEIVING_TDS },
}

/**
 * The bottom of the receptions board: a quarterback and a tight end who each
 * drew a target and caught nothing share rank 885, their 0s shown as 0.
 */
export const ReceptionsTail: Story = {
  args: { leaders: LEADERS_BY_RECEPTIONS_TAIL },
}

/**
 * The kicking board (issue #315): six sortable columns, FG% and 50+ derived
 * from the counts the API sent, the rows and ranks exactly as sent.
 */
export const ByFieldGoalsMade: Story = {
  args: { leaders: LEADERS_BY_FG_MADE },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement)
    await expect(
      canvas.getByRole('columnheader', { name: 'FG made' }),
    ).toHaveAttribute('aria-sort', 'descending')
    await expect(canvas.getByText('94.7%')).toBeInTheDocument()
    await expect(
      canvas.queryByRole('columnheader', { name: 'Starter record' }),
    ).toBeNull()
    await userEvent.click(canvas.getByRole('button', { name: '50+' }))
    await expect(args.onSort).toHaveBeenCalledWith('fg_made_50_plus')
  },
}

/** The kicking board by FG%, a sort the engine computes and does not send. */
export const ByFieldGoalPercentage: Story = {
  args: { leaders: LEADERS_BY_FG_PCT, describedBy: 'fg-pct-note' },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    await expect(
      canvas.getByRole('columnheader', { name: 'FG%' }),
    ).toHaveAttribute('aria-sort', 'descending')
  },
}

/**
 * The foot of the kicking board: three players tied at 79 who never made a
 * field goal. Their Long is a dash read as "none" -- never 0 -- and the
 * center with no attempt has no FG% either.
 */
export const KickingTail: Story = {
  args: { leaders: LEADERS_BY_FG_MADE_TAIL },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    await expect(canvas.getAllByRole('cell', { name: 'none' })).toHaveLength(4)
  },
}

/** The punting board (issue #315): four sortable columns, no Long. */
export const ByPuntingYards: Story = {
  args: { leaders: LEADERS_BY_PT_YARDS },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement)
    await expect(
      canvas.getByRole('columnheader', { name: 'Yards' }),
    ).toHaveAttribute('aria-sort', 'descending')
    await expect(canvas.getByText('4,831')).toBeInTheDocument()
    await userEvent.click(canvas.getByRole('button', { name: 'Inside 20' }))
    await expect(args.onSort).toHaveBeenCalledWith('pt_inside_20')
  },
}

/**
 * The defense board (issue #317): T.J. Watt's 19.0, then a real tie at 17.5
 * -- a half sack shown, never rounded -- with the founder's two notes (#316)
 * under the table, each marked on and describing the headers it covers.
 */
export const BySacks: Story = {
  args: { leaders: LEADERS_BY_DEF_SACKS },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement)
    await expect(
      canvas.getByRole('columnheader', { name: 'Sacks' }),
    ).toHaveAttribute('aria-sort', 'descending')
    await expect(canvas.getByText('19.0')).toBeInTheDocument()
    await expect(canvas.getAllByText('17.5')).toHaveLength(2)
    await expect(
      canvas.getByRole('button', { name: 'Sacks' }),
    ).toHaveAccessibleDescription(DEFENSE_EARLY_ERA_NOTE)
    await expect(
      canvas.getByRole('button', { name: 'Solo tackles' }),
    ).toHaveAccessibleDescription(DEFENSE_UNOFFICIAL_NOTE)
    await userEvent.click(canvas.getByRole('button', { name: 'Interceptions' }))
    await expect(args.onSort).toHaveBeenCalledWith('def_interceptions')
  },
}

/**
 * A defense board with a half sack (0.5) and stats the source didn't track:
 * "not recorded", never 0 or 0.0. Invented, since the fixture has no nulls.
 */
export const DefenseWithNullStats: Story = {
  args: { leaders: DEFENSE_WITH_NULL_STATS },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    await expect(canvas.getByText('0.5')).toBeInTheDocument()
    await expect(canvas.getAllByText('not recorded')).toHaveLength(6)
    await expect(canvas.getByText(DEFENSE_EARLY_ERA_NOTE)).toBeVisible()
    await expect(canvas.getByText(DEFENSE_UNOFFICIAL_NOTE)).toBeVisible()
  },
}

/** The foot of the sacks board: a receiver on one solo tackle, with 0.0 sacks. */
export const DefenseTail: Story = {
  args: { leaders: LEADERS_BY_DEF_SACKS_TAIL },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    await expect(
      canvas.getByRole('rowheader', { name: 'Zola Davis' }),
    ).toBeInTheDocument()
    await expect(canvas.getAllByText('0.0')).toHaveLength(3)
  },
}
