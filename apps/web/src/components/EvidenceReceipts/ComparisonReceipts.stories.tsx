import type { Meta, StoryObj } from '@storybook/react-vite'
import { expect, userEvent, within } from 'storybook/test'
import type { ComparisonResultOut } from '../../lib/api/types'
import { ComparisonReceipts } from './ComparisonReceipts'
import { TEXAS_ELO, USC_ELO } from './eloLedgerFixture'

const evidence: ComparisonResultOut = {
  year: 2020,
  method: 'keener',
  team_a: {
    team_id: 194,
    team_name: 'Ohio State',
    rank: 2,
    rating: 0.00877,
    wins: 7,
    losses: 1,
    ties: 0,
    rating_breakdown: {
      entries: [
        {
          opponent_team_id: 84,
          opponent_name: 'Indiana',
          games_played: 1,
          wins: 1,
          losses: 0,
          credit: 0.018,
          contribution: 0.002,
          explanation:
            "Snuck out a 24-21 win — 53% of the points, barely above even. That's the flat 0.60 every win banks, plus just a 0.01 margin bonus.",
        },
        {
          opponent_team_id: 127,
          opponent_name: 'Michigan State',
          games_played: 1,
          wins: 1,
          losses: 0,
          credit: 0.021,
          contribution: 0.00227,
          explanation:
            "Ran them off the field, 45-3 — 94% of the points, capped at 85% so blowouts don't count extra past that. That earns the flat 0.60 every win banks, plus a 0.10 margin bonus for the lopsided score.",
        },
      ],
      // Real, not negligible -- the Keener regularizer/eigenvalue baseline
      // (see RatingBreakdownDisclosure) typically accounts for ~47-53% of a
      // team's rating.
      residual_contribution: 0.0045,
    },
    elo_ledger: null,
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
    ties: 0,
    rating_breakdown: {
      entries: [
        {
          opponent_team_id: 84,
          opponent_name: 'Indiana',
          games_played: 1,
          wins: 0,
          losses: 1,
          credit: 0.01,
          contribution: 0.00102,
          explanation:
            'Got run over, 3-52 — 5% of the points, clamped at the 15% floor. Still banks the flat 0.05 every loss keeps, nobody walks away with zero, but no margin bonus at that end of the scale.',
        },
      ],
      residual_contribution: 0.005,
    },
    elo_ledger: null,
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
  // The engine's raw sentence, as the API sends it -- apps/web deliberately
  // doesn't render it (issue #24); the bottom line is built from the summaries.
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

/**
 * Issue #83: team A tied a common opponent, so its record reads W-L-T
 * ("6-9-1") and that side of the row carries its own neutral "T" tag,
 * announced as "Tie", while team B's side is still an ordinary loss.
 */
export const CommonOpponentTie: Story = {
  args: {
    evidence: {
      ...evidence,
      team_a: { ...evidence.team_a, wins: 6, losses: 9, ties: 1 },
      common_opponents: [
        {
          opponent_team_id: 84,
          opponent_name: 'Indiana',
          opponent_rank: 21,
          team_a_result: 'T',
          team_a_score: 26,
          team_a_opponent_score: 26,
          team_b_result: 'L',
          team_b_score: 21,
          team_b_opponent_score: 38,
        },
        ...evidence.common_opponents.slice(1),
      ],
    },
  },
}

/**
 * Demonstrates issue #31's hover-triggered rating breakdown -- hover (or Tab
 * to focus, then press Enter) either team's rating value to see the
 * per-opponent credit that adds up to it, including the honestly-labeled
 * "Rating-system baseline" residual (see `RatingBreakdownDisclosure`).
 */
export const RatingBreakdown: Story = {
  args: {
    evidence,
  },
}

const texasVsUscElo: ComparisonResultOut = {
  ...evidence,
  year: 2005,
  method: 'elo',
  team_a: {
    ...evidence.team_a,
    team_id: TEXAS_ELO.team_id,
    team_name: TEXAS_ELO.team_name,
    rank: 1,
    rating: TEXAS_ELO.rating,
    wins: TEXAS_ELO.wins,
    losses: TEXAS_ELO.losses,
    ties: TEXAS_ELO.ties,
    rating_breakdown: { entries: [], residual_contribution: 0 },
    elo_ledger: TEXAS_ELO.elo_ledger,
  },
  team_b: {
    ...evidence.team_b,
    team_id: USC_ELO.team_id,
    team_name: USC_ELO.team_name,
    rank: 2,
    rating: USC_ELO.rating,
    wins: USC_ELO.wins,
    losses: USC_ELO.losses,
    ties: USC_ELO.ties,
    rating_breakdown: { entries: [], residual_contribution: 0 },
    elo_ledger: USC_ELO.elo_ledger,
  },
  common_opponents: [],
  rating_diff: TEXAS_ELO.rating - USC_ELO.rating,
  verdict: 'Texas rates higher overall (1661.4 vs 1526.9, rank 1 vs 2).',
}

/**
 * An Elo comparison (epic #147 / issues #82, #183): ratings, the rating diff
 * and the bottom line all print on Elo's own whole-point scale ("1,661 vs
 * 1,527"), and each team's rating opens that team's own game-by-game ledger.
 */
export const EloLeader: Story = {
  args: { evidence: texasVsUscElo },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    await expect(canvas.getAllByRole('button')).toHaveLength(2)
    await userEvent.hover(canvas.getByRole('button', { name: '1,527' }))
    await expect(
      await canvas.findByRole('dialog', {
        name: 'USC Elo rating, game by game',
      }),
    ).toBeVisible()
    await expect(canvasElement.textContent).not.toMatch(/Keener/)
  },
}

/** Career Elo: plain ratings, and one line for the whole block says why there is nothing to open. */
export const EloCareer: Story = {
  args: {
    evidence: {
      ...texasVsUscElo,
      method: 'elo_career',
      team_a: { ...texasVsUscElo.team_a, elo_ledger: null },
      team_b: { ...texasVsUscElo.team_b, elo_ledger: null },
    },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    await expect(canvas.queryByRole('button')).toBeNull()
    await expect(
      canvas.getAllByText(
        "Career Elo carries ratings across seasons, and its game-by-game work isn't shown yet.",
      ),
    ).toHaveLength(1)
  },
}

/**
 * Two Elo ratings under a point apart both print "1,531", so the bottom line
 * says they rate the same at display precision instead of naming a leader
 * beside two identical numbers (#149's web half).
 */
export const EloEqualAtDisplayPrecision: Story = {
  args: {
    evidence: {
      ...evidence,
      method: 'elo',
      team_a: {
        ...evidence.team_a,
        team_name: 'UNLV',
        rank: 60,
        rating: 1531.24,
        rating_breakdown: { entries: [], residual_contribution: 0 },
      },
      team_b: {
        ...evidence.team_b,
        team_name: 'Nevada',
        rank: 61,
        rating: 1530.9,
        rating_breakdown: { entries: [], residual_contribution: 0 },
      },
      common_opponents: [],
      rating_diff: 1531.24 - 1530.9,
      verdict: 'UNLV rates higher overall (1531.24 vs 1530.9, rank 60 vs 61).',
    },
  },
}
