import type { Meta, StoryObj } from '@storybook/react-vite'
import { fn } from 'storybook/test'
import type { ComparisonEnvelope, TeamCaseEnvelope } from '../../lib/api/types'
import { VerdictCard } from './VerdictCard'

const teamCaseEnvelope: TeamCaseEnvelope = {
  evidence: {
    year: 2005,
    method: 'keener',
    team_id: 1,
    team_name: 'Texas',
    rank: 1,
    rating: 12.3,
    wins: 13,
    losses: 0,
    games: [],
    quality_wins: [
      {
        opponent_team_id: 2,
        opponent_name: 'Michigan',
        opponent_rank: 3,
        opponent_rating: 9.5,
        result: 'W',
        team_score: 27,
        opponent_score: 14,
        week: 5,
        season_type: 'regular',
        neutral_site: false,
      },
    ],
    worst_loss: null,
  },
  narration: {
    text: "Texas went 13-0 and beat everybody worth beating. That's the champ, no debate needed.",
    contested: false,
    cached: false,
  },
}

const comparisonEnvelope: ComparisonEnvelope = {
  evidence: {
    year: 2005,
    team_a: { team_name: 'Texas', rank: 1, rating: 12.3 },
    team_b: { team_name: 'USC', rank: 2, rating: 11.9 },
    head_to_head: { played: false, meetings: [] },
    common_opponents: [{ opponent_name: 'Ohio State' }],
    rating_diff: 0.4,
    verdict: 'Texas was better -- higher rating, better résumé.',
  },
  narration: {
    text: "It's close, but Texas edges USC. Reasonable people can disagree here.",
    contested: true,
    cached: true,
  },
}

const meta = {
  title: 'components/VerdictCard',
  component: VerdictCard,
  tags: ['autodocs'],
  args: {
    onSelectYear: fn(),
    onSelectCandidate: fn(),
  },
} satisfies Meta<typeof VerdictCard>

export default meta

type Story = StoryObj<typeof meta>

export const Loading: Story = {
  args: {
    state: { status: 'loading' },
  },
}

export const TeamCaseSuccess: Story = {
  args: {
    state: { status: 'success', envelope: teamCaseEnvelope },
  },
}

export const ComparisonSuccess: Story = {
  args: {
    state: { status: 'success', envelope: comparisonEnvelope },
  },
}

export const UnknownYearError: Story = {
  args: {
    state: {
      status: 'error',
      error: {
        kind: 'unknown_year',
        body: {
          error: 'unknown_year',
          year: 1899,
          available_years: [2003, 2004, 2005],
        },
      },
    },
  },
}

export const AmbiguousTeamError: Story = {
  args: {
    state: {
      status: 'error',
      error: {
        kind: 'ambiguous_team',
        body: {
          error: 'ambiguous_team',
          query: 'Texas St',
          candidates: ['Texas', 'Texas State'],
        },
      },
    },
  },
}

export const SameTeamComparisonError: Story = {
  args: {
    state: {
      status: 'error',
      error: {
        kind: 'same_team_comparison',
        body: { error: 'same_team_comparison', team_name: 'Texas' },
      },
    },
  },
}

export const NetworkError: Story = {
  args: {
    state: {
      status: 'error',
      error: {
        kind: 'network_error',
        message:
          'Could not reach the API. Check your connection and try again.',
      },
    },
  },
}
