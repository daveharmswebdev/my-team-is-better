import type { Meta, StoryObj } from '@storybook/react-vite'
import { MemoryRouter } from 'react-router-dom'
import { DATA_SOURCES } from '../../lib/playerFixtures'
import { PlayerStatsCredit } from './PlayerStatsCredit'

const meta = {
  title: 'components/PlayerStatsCredit',
  component: PlayerStatsCredit,
  tags: ['autodocs'],
  args: {
    credit: DATA_SOURCES[2] ?? null,
  },
  decorators: [
    (Story) => (
      <MemoryRouter>
        <Story />
      </MemoryRouter>
    ),
  ],
} satisfies Meta<typeof PlayerStatsCredit>

export default meta

type Story = StoryObj<typeof meta>

/** The live `nflverse_player_stats` credit. */
export const Credited: Story = {}

/** EPA on screen (a QB score #459, an EPA board or column #347): the EP model credited beside the stats. */
export const WithEpModel: Story = {
  args: { epModel: true },
}

/** No credit in hand (loading, or `/api/credits` failed): a link to the About page's data. */
export const Unavailable: Story = {
  args: { credit: null },
}
