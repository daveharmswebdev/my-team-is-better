import type { Meta, StoryObj } from '@storybook/react-vite'
import type { ComparisonResultOut } from '../../lib/api/types'
import { ComparisonReceipts } from './ComparisonReceipts'

const evidence: ComparisonResultOut = {
  year: 2020,
  team_a: {
    team_id: 194,
    team_name: 'Ohio State',
    rank: 2,
    rating: 0.00877,
    wins: 7,
    losses: 1,
    quality_wins: [],
    worst_loss: null,
  },
  team_b: {
    team_id: 130,
    team_name: 'Michigan',
    rank: 95,
    rating: 0.00602,
    wins: 2,
    losses: 4,
    quality_wins: [],
    worst_loss: null,
  },
  head_to_head: { played: false, meetings: [] },
  common_opponents: [
    {
      opponent_team_id: 84,
      opponent_name: 'Indiana',
      opponent_rank: 21,
      team_a_result: 'W',
      team_a_score: 42,
      team_a_opponent_score: 35,
      team_b_result: 'L',
      team_b_score: 21,
      team_b_opponent_score: 38,
    },
    {
      opponent_team_id: 127,
      opponent_name: 'Michigan State',
      opponent_rank: 101,
      team_a_result: 'W',
      team_a_score: 52,
      team_a_opponent_score: 12,
      team_b_result: 'L',
      team_b_score: 24,
      team_b_opponent_score: 27,
    },
  ],
  rating_diff: 0.00275,
  verdict:
    'Ohio State rates higher overall (0.008771 vs 0.006022, rank 2 vs 95).',
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

export const HeadToHeadPlayed: Story = {
  args: {
    evidence: {
      ...evidence,
      head_to_head: {
        played: true,
        meetings: [
          {
            week: 13,
            season_type: 'regular',
            neutral_site: false,
            home_team: 'Ohio State',
            away_team: 'Michigan',
            home_points: 21,
            away_points: 14,
            winner: 'Ohio State',
          },
        ],
      },
    },
  },
}

export const NoCommonOpponents: Story = {
  args: {
    evidence: {
      ...evidence,
      common_opponents: [],
    },
  },
}
