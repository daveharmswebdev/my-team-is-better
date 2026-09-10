import type { Meta, StoryObj } from '@storybook/react-vite'
import type { ComparisonResultOut } from '../../lib/api/types'
import { ComparisonReceipts } from './ComparisonReceipts'

const evidence: ComparisonResultOut = {
  year: 2005,
  team_a: {
    team_id: 1,
    team_name: 'Texas',
    rank: 1,
    rating: 12.3,
    wins: 13,
    losses: 0,
  },
  team_b: {
    team_id: 2,
    team_name: 'USC',
    rank: 2,
    rating: 11.9,
    wins: 12,
    losses: 1,
  },
  head_to_head: { played: false, meetings: [] },
  common_opponents: [
    { opponent_name: 'Ohio State' },
    { opponent_name: 'Oklahoma' },
  ],
  rating_diff: 0.4,
  verdict: 'Texas was better -- higher rating, better résumé.',
}

const meta = {
  title: 'components/EvidenceReceipts/ComparisonReceipts',
  component: ComparisonReceipts,
  tags: ['autodocs'],
} satisfies Meta<typeof ComparisonReceipts>

export default meta

type Story = StoryObj<typeof meta>

export const Default: Story = {
  args: {
    evidence,
  },
}
