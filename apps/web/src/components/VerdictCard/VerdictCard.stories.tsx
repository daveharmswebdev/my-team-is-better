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
    rating: 0.01234,
    wins: 13,
    losses: 0,
    ties: 0,
    rating_breakdown: {
      entries: [
        {
          opponent_team_id: 2,
          opponent_name: 'Michigan',
          games_played: 1,
          wins: 1,
          losses: 0,
          credit: 0.02,
          contribution: 0.006,
          explanation:
            "Ran them off the field, 45-3 — 94% of the points, capped at 85% so blowouts don't count extra past that. That earns the flat 0.60 every win banks, plus a 0.10 margin bonus for the lopsided score.",
        },
      ],
      residual_contribution: 0.00634,
    },
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
    team_a: {
      team_id: 1,
      team_name: 'Texas',
      rank: 1,
      rating: 0.01234,
      wins: 13,
      losses: 0,
      ties: 0,
      rating_breakdown: {
        entries: [
          {
            opponent_team_id: 3,
            opponent_name: 'Ohio State',
            games_played: 1,
            wins: 1,
            losses: 0,
            credit: 0.019,
            contribution: 0.0057,
            explanation:
              "Snuck out a 24-21 win — 53% of the points, barely above even. That's the flat 0.60 every win banks, plus just a 0.01 margin bonus.",
          },
        ],
        residual_contribution: 0.00664,
      },
      quality_wins: [],
      worst_loss: null,
    },
    team_b: {
      team_id: 2,
      team_name: 'USC',
      rank: 2,
      rating: 0.01147,
      wins: 12,
      losses: 1,
      ties: 0,
      rating_breakdown: {
        entries: [
          {
            opponent_team_id: 3,
            opponent_name: 'Ohio State',
            games_played: 1,
            wins: 0,
            losses: 1,
            credit: 0.015,
            contribution: 0.0045,
            explanation:
              'Got run over, 3-52 — 5% of the points, clamped at the 15% floor. Still banks the flat 0.05 every loss keeps, nobody walks away with zero, but no margin bonus at that end of the scale.',
          },
        ],
        residual_contribution: 0.00697,
      },
      quality_wins: [],
      worst_loss: null,
    },
    head_to_head: { played: false, meetings: [] },
    common_opponents: [
      {
        opponent_team_id: 3,
        opponent_name: 'Ohio State',
        opponent_rank: 4,
        team_a_result: 'W',
        team_a_score: 38,
        team_a_opponent_score: 24,
        team_b_result: 'L',
        team_b_score: 17,
        team_b_opponent_score: 20,
      },
    ],
    rating_diff: 0.00087,
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

/**
 * `unknown_team` -- a not-found state with no pick list at all, by contract
 * (correction pills were removed from this error kind).
 */
export const UnknownTeamErrorNotFound: Story = {
  args: {
    state: {
      status: 'error',
      error: {
        kind: 'unknown_team',
        body: {
          error: 'unknown_team',
          query: 'Abilene Christian',
          year: 2010,
          sport: 'cfb',
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
