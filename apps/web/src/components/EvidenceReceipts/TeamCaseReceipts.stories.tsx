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

const openerWin = {
  opponent_team_id: 3,
  opponent_name: 'LSU',
  opponent_rank: null,
  opponent_rating: 4.2,
  result: 'W' as const,
  team_score: 24,
  opponent_score: 17,
  week: 1,
  season_type: 'regular',
  neutral_site: false,
}

const midseasonWin = {
  opponent_team_id: 4,
  opponent_name: 'Tennessee',
  opponent_rank: null,
  opponent_rating: 3.9,
  result: 'W' as const,
  team_score: 31,
  opponent_score: 10,
  week: 10,
  season_type: 'regular',
  neutral_site: false,
}

const lateSeasonWin = {
  opponent_team_id: 5,
  opponent_name: 'Oklahoma',
  opponent_rank: 8,
  opponent_rating: 8.1,
  result: 'W' as const,
  team_score: 20,
  opponent_score: 13,
  week: 12,
  season_type: 'regular',
  neutral_site: true,
}

const bowlWin = {
  opponent_team_id: 6,
  opponent_name: 'USC',
  opponent_rank: 2,
  opponent_rating: 9.8,
  result: 'W' as const,
  team_score: 41,
  opponent_score: 38,
  // Bowl weeks are numbered independently of the regular season upstream,
  // so this can carry the same raw `week` as an early regular-season game.
  week: 1,
  season_type: 'postseason',
  neutral_site: true,
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
  games: [openerWin, qualityWin, midseasonWin, lateSeasonWin, bowlWin],
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

const worstLoss = {
  opponent_team_id: 7,
  opponent_name: 'Baylor',
  opponent_rank: null,
  opponent_rating: 2.1,
  result: 'L' as const,
  team_score: 14,
  opponent_score: 27,
  week: 8,
  season_type: 'regular',
  neutral_site: false,
}

export const WithALoss: Story = {
  args: {
    evidence: {
      ...undefeated,
      wins: 11,
      losses: 1,
      // Baylor is a distinct opponent (its own `opponent_team_id`/`week`),
      // present in both `games` and `worst_loss` -- the realistic shape a
      // real API response has, same as `qualityWin`/Michigan above.
      games: [...undefeated.games, worstLoss],
      worst_loss: worstLoss,
    },
  },
}
