import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { ComparisonResultOut } from '../../lib/api/types'
import { ComparisonReceipts } from './ComparisonReceipts'

const evidence: ComparisonResultOut = {
  year: 2005,
  team_a: {
    team_id: 1,
    team_name: 'Texas',
    rank: 1,
    rating: 12.3,
    wins: 13,
    losses: 0,
  },
  team_b: {
    team_id: 2,
    team_name: 'USC',
    rank: 2,
    rating: 11.9,
    wins: 12,
    losses: 1,
  },
  head_to_head: { played: true, meetings: [{ winner: 'Texas' }] },
  common_opponents: [{ opponent_name: 'Ohio State' }],
  rating_diff: 0.4,
  verdict: 'Texas was better.',
}

describe('ComparisonReceipts', () => {
  it('renders team_a and team_b fields generically', () => {
    render(<ComparisonReceipts evidence={evidence} />)

    expect(screen.getByText('Texas')).toBeInTheDocument()
    expect(screen.getByText('USC')).toBeInTheDocument()
  })

  it('renders the rating diff and verdict', () => {
    render(<ComparisonReceipts evidence={evidence} />)

    expect(screen.getByText(/0.4/)).toBeInTheDocument()
    expect(screen.getByText('Texas was better.')).toBeInTheDocument()
  })

  it('renders common opponents', () => {
    render(<ComparisonReceipts evidence={evidence} />)

    expect(screen.getByText(/Ohio State/)).toBeInTheDocument()
  })
})
