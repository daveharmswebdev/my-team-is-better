import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
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

const lsuGame = {
  ...baseOpponent,
  opponent_team_id: 3,
  opponent_name: 'LSU',
  opponent_rank: null,
  result: 'W' as const,
  team_score: 24,
  opponent_score: 17,
  week: 1,
  season_type: 'regular',
}

const tennesseeGame = {
  ...baseOpponent,
  opponent_team_id: 4,
  opponent_name: 'Tennessee',
  opponent_rank: null,
  result: 'W' as const,
  team_score: 31,
  opponent_score: 10,
  week: 10,
  season_type: 'regular',
}

const bowlGame = {
  ...baseOpponent,
  opponent_team_id: 5,
  opponent_name: 'USC',
  opponent_rank: 2,
  result: 'W' as const,
  team_score: 41,
  opponent_score: 38,
  // Postseason weeks are numbered independently of the regular season by
  // the upstream data (a bowl game can carry week: 1), so sorting on raw
  // week number alone would interleave it into the regular season.
  week: 1,
  season_type: 'postseason',
}

const evidence: TeamCaseOut = {
  year: 2005,
  method: 'keener',
  team_id: 1,
  team_name: 'Texas',
  rank: 1,
  rating: 0.01234,
  wins: 13,
  losses: 0,
  // Real entries (not just a residual-only placeholder) so this component's
  // tests can exercise the same rating breakdown disclosure ComparisonReceipts
  // already tests -- contribution + residual sum exactly to `rating`
  // (0.005 + 0.00734 = 0.01234).
  rating_breakdown: {
    entries: [
      {
        opponent_team_id: 2,
        opponent_name: 'Michigan',
        games_played: 1,
        wins: 1,
        losses: 0,
        credit: 0.03,
        contribution: 0.005,
      },
    ],
    residual_contribution: 0.00734,
  },
  // `baseOpponent` (Michigan) is included in both `games` and
  // `quality_wins` here on purpose -- a real API response includes every
  // quality win (and the worst loss, if any) in the full game list too, so
  // the fixture should exercise that overlap rather than avoid it.
  games: [bowlGame, tennesseeGame, lsuGame, baseOpponent],
  quality_wins: [baseOpponent],
  worst_loss: null,
}

describe('TeamCaseReceipts', () => {
  it('renders the win-loss record', () => {
    render(<TeamCaseReceipts evidence={evidence} />)

    expect(screen.getByText(/13-0/)).toBeInTheDocument()
  })

  it('renders the rating scaled by 1000 via formatRating, not the raw eigenvector value', () => {
    render(<TeamCaseReceipts evidence={evidence} />)

    expect(screen.getByText(/12\.34/)).toBeInTheDocument()
  })

  it('renders quality wins', () => {
    render(<TeamCaseReceipts evidence={evidence} />)

    // Michigan is a quality win that also appears in the full schedule (the
    // realistic API shape), so it legitimately renders twice.
    expect(screen.getAllByText(/Michigan/)).toHaveLength(2)
  })

  it('stars the full-schedule row for a game that is also a quality win, instead of an unexplained duplicate', () => {
    render(<TeamCaseReceipts evidence={evidence} />)

    const schedule = screen.getByRole('list', { name: /full schedule/i })
    const michiganRow = within(schedule)
      .getByText(/Michigan/)
      .closest('li')

    expect(michiganRow).not.toBeNull()
    expect(
      within(michiganRow as HTMLElement).getByText(/quality win/i),
    ).toBeInTheDocument()

    // The Quality Wins section itself has no redundant badge on its own row.
    const qualityWins = screen.getByRole('list', { name: /quality wins/i })
    expect(
      within(qualityWins).queryByText(/quality win/i),
    ).not.toBeInTheDocument()
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

  it('renders every game in the full schedule, not just quality wins and worst loss', () => {
    render(<TeamCaseReceipts evidence={evidence} />)

    // LSU and Tennessee appear only in `games`, not in `quality_wins` or
    // `worst_loss` -- a fan should still be able to see them.
    expect(screen.getByText(/LSU/)).toBeInTheDocument()
    expect(screen.getByText(/Tennessee/)).toBeInTheDocument()
  })

  it('orders the full schedule chronologically by regular-season week, with postseason games after the regular season regardless of raw week number', () => {
    render(<TeamCaseReceipts evidence={evidence} />)

    const schedule = screen.getByRole('list', { name: /full schedule/i })
    const opponents = within(schedule)
      .getAllByRole('listitem')
      .map((item) => item.textContent)

    const lsuIndex = opponents.findIndex((text) => text?.includes('LSU'))
    const tennesseeIndex = opponents.findIndex((text) =>
      text?.includes('Tennessee'),
    )
    const bowlIndex = opponents.findIndex((text) => text?.includes('USC'))

    // Regular season in week order (LSU: week 1, Tennessee: week 10)...
    expect(lsuIndex).toBeLessThan(tennesseeIndex)
    // ...then the postseason, even though the bowl game's raw `week` (1) is
    // lower than Tennessee's.
    expect(tennesseeIndex).toBeLessThan(bowlIndex)
  })

  it('wires the rating value up to its rating breakdown disclosure, rendering real entries', async () => {
    const user = userEvent.setup()
    render(<TeamCaseReceipts evidence={evidence} />)

    const ratingTrigger = screen.getByRole('button', { name: /12\.34/ })
    await user.hover(ratingTrigger)

    const dialog = screen.getByRole('dialog')
    expect(within(dialog).getByText('Michigan')).toBeInTheDocument()
    expect(
      within(dialog).getByText(/rating-system baseline/i),
    ).toBeInTheDocument()

    await user.unhover(ratingTrigger)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })
})
