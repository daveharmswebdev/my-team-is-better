import type { Meta, StoryObj } from '@storybook/react-vite'
import type { TeamCaseOut } from '../../lib/api/types'
import { TeamCaseReceipts } from './TeamCaseReceipts'

const qualityWin = {
  opponent_team_id: 2,
  opponent_name: 'Michigan',
  opponent_rank: 3,
  opponent_rating: 9.5,
  result: 'W' as const,
  team_score: 27,
  opponent_score: 14,
  week: 5,
  season_type: 'regular',
  neutral_site: false,
}

const undefeated: TeamCaseOut = {
  year: 2005,
  method: 'keener',
  team_id: 1,
  team_name: 'Texas',
  rank: 1,
  rating: 0.01234,
  wins: 13,
  losses: 0,
  games: [qualityWin],
  quality_wins: [qualityWin],
  worst_loss: null,
}

const meta = {
  title: 'components/EvidenceReceipts/TeamCaseReceipts',
  component: TeamCaseReceipts,
  tags: ['autodocs'],
} satisfies Meta<typeof TeamCaseReceipts>

export default meta

type Story = StoryObj<typeof meta>

export const Undefeated: Story = {
  args: {
    evidence: undefeated,
  },
}

export const WithALoss: Story = {
  args: {
    evidence: {
      ...undefeated,
      wins: 11,
      losses: 1,
      worst_loss: {
        ...qualityWin,
        opponent_name: 'Baylor',
        opponent_rank: null,
        result: 'L',
      },
    },
  },
}
