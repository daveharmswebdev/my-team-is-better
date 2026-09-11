import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
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
    // Each entry carries its own `opponent_name` straight from the API now
    // (issue #31 follow-up) -- no more resolving names from elsewhere in the
    // evidence. Contributions + residual sum exactly to `rating` (0.002 +
    // 0.0015 + 0.001 + 0.00427 = 0.00877).
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
          opponent_team_id: 555,
          opponent_name: 'Northwestern',
          games_played: 1,
          wins: 1,
          losses: 0,
          credit: 0.015,
          contribution: 0.0015,
          explanation:
            "Ran them off the field, 45-3 — 94% of the points, capped at 85% so blowouts don't count extra past that. That earns the flat 0.60 every win banks, plus a 0.10 margin bonus for the lopsided score.",
        },
        {
          opponent_team_id: 999,
          opponent_name: 'Rutgers',
          games_played: 1,
          wins: 1,
          losses: 0,
          credit: 0.009,
          contribution: 0.001,
          explanation:
            "Snuck out a 24-21 win — 53% of the points, barely above even. That's the flat 0.60 every win banks, plus just a 0.01 margin bonus.",
        },
      ],
      residual_contribution: 0.00427,
    },
    quality_wins: [
      {
        opponent_team_id: 555,
        opponent_name: 'Northwestern',
        opponent_rank: 45,
        opponent_rating: 0.003,
        result: 'W',
        team_score: 38,
        opponent_score: 21,
        week: 6,
        season_type: 'regular',
        neutral_site: false,
      },
    ],
    worst_loss: null,
  },
  team_b: {
    team_id: 130,
    team_name: 'Michigan',
    rank: 95,
    rating: 0.00602,
    wins: 2,
    losses: 4,
    // Contribution + residual sum exactly to `rating` (0.00102 + 0.005 =
    // 0.00602).
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
    quality_wins: [],
    worst_loss: null,
  },
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
  ],
  rating_diff: 0.00275,
  verdict: 'Ohio State was better.',
}

describe('ComparisonReceipts', () => {
  it('renders team_a and team_b names and formatted ratings', () => {
    render(<ComparisonReceipts evidence={evidence} />)

    expect(screen.getByText('Ohio State')).toBeInTheDocument()
    expect(screen.getByText('Michigan')).toBeInTheDocument()
    expect(screen.getByText('8.77')).toBeInTheDocument()
    expect(screen.getByText('6.02')).toBeInTheDocument()
  })

  it('renders the win-loss record per team', () => {
    render(<ComparisonReceipts evidence={evidence} />)

    expect(screen.getByText('7-1')).toBeInTheDocument()
    expect(screen.getByText('2-4')).toBeInTheDocument()
  })

  it('renders the formatted rating diff and verdict', () => {
    render(<ComparisonReceipts evidence={evidence} />)

    expect(screen.getByText(/2\.75/)).toBeInTheDocument()
    expect(screen.getByText(/Ohio State was better\./)).toBeInTheDocument()
  })

  it('renders head-to-head meetings with real scores when they played', () => {
    render(<ComparisonReceipts evidence={evidence} />)

    expect(screen.getByText(/Ohio State 21-14 Michigan/)).toBeInTheDocument()
  })

  it('renders a "did not play" message when they never met', () => {
    render(
      <ComparisonReceipts
        evidence={{
          ...evidence,
          head_to_head: { played: false, meetings: [] },
        }}
      />,
    )

    expect(
      screen.getByText('Ohio State and Michigan did not play each other.'),
    ).toBeInTheDocument()
  })

  it('renders common opponents with both teams W/L results', () => {
    render(<ComparisonReceipts evidence={evidence} />)

    expect(screen.getByText(/Indiana/)).toBeInTheDocument()
    expect(screen.getByText(/#21/)).toBeInTheDocument()
  })

  it('renders "No common opponents" when there are none', () => {
    render(
      <ComparisonReceipts evidence={{ ...evidence, common_opponents: [] }} />,
    )

    expect(screen.getByText('No common opponents.')).toBeInTheDocument()
  })

  it('renders no raw JSON output', () => {
    const { container } = render(<ComparisonReceipts evidence={evidence} />)

    expect(container.textContent).not.toContain('{')
    expect(container.textContent).not.toContain('[object')
  })

  it('wires each team’s rating value up to its own rating breakdown disclosure, rendering each entry’s own opponent_name', async () => {
    const user = userEvent.setup()
    render(<ComparisonReceipts evidence={evidence} />)

    const ratingTrigger = screen.getByRole('button', { name: /8\.77/ })
    await user.hover(ratingTrigger)

    const dialog = screen.getByRole('dialog')
    // Every row's name comes straight from its entry's own opponent_name.
    expect(within(dialog).getByText('Indiana')).toBeInTheDocument()
    expect(within(dialog).getByText('Northwestern')).toBeInTheDocument()
    expect(within(dialog).getByText('Rutgers')).toBeInTheDocument()
    expect(
      within(dialog).getByText(/rating-system baseline/i),
    ).toBeInTheDocument()

    await user.unhover(ratingTrigger)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })
})
