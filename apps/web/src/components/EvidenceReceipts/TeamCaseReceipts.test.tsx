import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { TeamCaseOut } from '../../lib/api/types'
import { TeamCaseReceipts } from './TeamCaseReceipts'

const baseOpponent = {
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

const evidence: TeamCaseOut = {
  year: 2005,
  method: 'keener',
  team_id: 1,
  team_name: 'Texas',
  rank: 1,
  rating: 12.3,
  wins: 13,
  losses: 0,
  games: [baseOpponent],
  quality_wins: [baseOpponent],
  worst_loss: null,
}

describe('TeamCaseReceipts', () => {
  it('renders the win-loss record', () => {
    render(<TeamCaseReceipts evidence={evidence} />)

    expect(screen.getByText(/13-0/)).toBeInTheDocument()
  })

  it('renders quality wins', () => {
    render(<TeamCaseReceipts evidence={evidence} />)

    expect(screen.getByText(/Michigan/)).toBeInTheDocument()
  })

  it('renders "no losses" when there is no worst loss', () => {
    render(<TeamCaseReceipts evidence={evidence} />)

    expect(screen.getByText(/no losses/i)).toBeInTheDocument()
  })

  it('renders the worst loss when present', () => {
    render(
      <TeamCaseReceipts
        evidence={{
          ...evidence,
          losses: 1,
          worst_loss: { ...baseOpponent, opponent_name: 'Baylor', result: 'L' },
        }}
      />,
    )

    expect(screen.getByText(/Baylor/)).toBeInTheDocument()
  })
})
