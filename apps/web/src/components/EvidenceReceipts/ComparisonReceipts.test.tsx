import { render, screen } from '@testing-library/react'
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
})
