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
    // Deliberately mixes: an opponent resolvable via `common_opponents`
    // (Indiana, id 84), one resolvable via this team's own `quality_wins`
    // (Northwestern, id 555), and one with no name anywhere in the evidence
    // (id 999) so the breakdown's opponent-name fallback is exercised too.
    // Contributions + residual sum exactly to `rating` (0.002 + 0.0015 +
    // 0.001 + 0.00427 = 0.00877).
    rating_breakdown: {
      entries: [
        {
          opponent_team_id: 84,
          games_played: 1,
          wins: 1,
          losses: 0,
          credit: 0.018,
          contribution: 0.002,
        },
        {
          opponent_team_id: 555,
          games_played: 1,
          wins: 1,
          losses: 0,
          credit: 0.015,
          contribution: 0.0015,
        },
        {
          opponent_team_id: 999,
          games_played: 1,
          wins: 1,
          losses: 0,
          credit: 0.009,
          contribution: 0.001,
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
          games_played: 1,
          wins: 0,
          losses: 1,
          credit: 0.01,
          contribution: 0.00102,
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

  it('wires each team’s rating value up to its own rating breakdown disclosure, resolving opponent names from quality_wins/common_opponents where available', async () => {
    const user = userEvent.setup()
    render(<ComparisonReceipts evidence={evidence} />)

    const ratingTrigger = screen.getByRole('button', { name: /8\.77/ })
    await user.hover(ratingTrigger)

    const dialog = screen.getByRole('dialog')
    // Resolved via `common_opponents` (Indiana, shared by both teams).
    expect(within(dialog).getByText(/Indiana/)).toBeInTheDocument()
    // Resolved via team_a's own `quality_wins` (Northwestern).
    expect(within(dialog).getByText(/Northwestern/)).toBeInTheDocument()
    // Not resolvable anywhere in the evidence -- numeric fallback, not a
    // guessed name.
    expect(within(dialog).getByText(/999/)).toBeInTheDocument()
    expect(
      within(dialog).getByText(/rating-system baseline/i),
    ).toBeInTheDocument()

    await user.unhover(ratingTrigger)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })
})
