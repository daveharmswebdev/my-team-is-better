import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
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
    quality_wins: [],
    worst_loss: null,
  },
  narration: {
    text: 'Texas was the best team in 2005, full stop.',
    contested: false,
    cached: false,
  },
}

const comparisonEnvelope: ComparisonEnvelope = {
  evidence: {
    year: 2005,
    team_a: { team_name: 'Texas' },
    team_b: { team_name: 'USC' },
    head_to_head: {},
    common_opponents: [],
    rating_diff: 0.4,
    verdict: 'Texas was better.',
  },
  narration: { text: 'Texas edges USC.', contested: true, cached: true },
}

describe('VerdictCard', () => {
  it('renders a loading state', () => {
    render(<VerdictCard state={{ status: 'loading' }} />)

    expect(screen.getByRole('status')).toHaveTextContent(/getting the verdict/i)
  })

  it('renders the narration and team-case receipts on success', () => {
    render(
      <VerdictCard state={{ status: 'success', envelope: teamCaseEnvelope }} />,
    )

    expect(
      screen.getByText('Texas was the best team in 2005, full stop.'),
    ).toBeInTheDocument()
    expect(screen.getByText(/13-0/)).toBeInTheDocument()
  })

  it('renders the narration and comparison receipts on success', () => {
    render(
      <VerdictCard
        state={{ status: 'success', envelope: comparisonEnvelope }}
      />,
    )

    expect(screen.getByText('Texas edges USC.')).toBeInTheDocument()
    expect(screen.getByText('Texas was better.')).toBeInTheDocument()
  })

  it('renders the unknown_year error state', () => {
    render(
      <VerdictCard
        state={{
          status: 'error',
          error: {
            kind: 'unknown_year',
            body: {
              error: 'unknown_year',
              year: 1899,
              available_years: [2004],
            },
          },
        }}
      />,
    )

    expect(screen.getByRole('alert')).toHaveTextContent(/1899/)
  })

  it('renders the ambiguous_team error state', () => {
    render(
      <VerdictCard
        state={{
          status: 'error',
          error: {
            kind: 'ambiguous_team',
            body: {
              error: 'ambiguous_team',
              query: 'Texas St',
              candidates: ['Texas State'],
            },
          },
        }}
      />,
    )

    expect(screen.getByRole('alert')).toHaveTextContent(/did you mean/i)
  })

  it('renders the same_team_comparison error state', () => {
    render(
      <VerdictCard
        state={{
          status: 'error',
          error: {
            kind: 'same_team_comparison',
            body: { error: 'same_team_comparison', team_name: 'Texas' },
          },
        }}
      />,
    )

    expect(screen.getByRole('alert')).toHaveTextContent(/texas/i)
  })

  it('renders a generic network error state', () => {
    render(
      <VerdictCard
        state={{
          status: 'error',
          error: { kind: 'network_error', message: 'Could not reach the API.' },
        }}
      />,
    )

    expect(screen.getByRole('alert')).toHaveTextContent(
      /could not reach the api/i,
    )
  })
})
