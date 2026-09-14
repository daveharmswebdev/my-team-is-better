import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import type { TeamCaseOut } from '../../lib/api/types'
import { TeamCaseReceipts } from './TeamCaseReceipts'
import { TEXAS_ELO } from './eloLedgerFixture'

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
  ties: 0,
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
        explanation:
          "Ran them off the field, 45-3 — 94% of the points, capped at 85% so blowouts don't count extra past that. That earns the flat 0.60 every win banks, plus a 0.10 margin bonus for the lopsided score.",
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

/** The result tag (W/L/T pill) inside a single game row. */
function resultTagIn(row: HTMLElement): HTMLElement {
  const tag = row.querySelector<HTMLElement>('[class*="gamelineTag"]')
  if (tag === null) {
    throw new Error('no result tag in row')
  }
  return tag
}

// Issue #83: an NFL tie carried through from the engine -- 8-8-1 overall
// with one tied game (26-26) on the schedule.
const tiedGame = {
  ...baseOpponent,
  opponent_team_id: 16,
  opponent_name: 'Minnesota Vikings',
  opponent_rank: null,
  result: 'T' as const,
  team_score: 26,
  opponent_score: 26,
  week: 7,
  season_type: 'regular',
}

const tiedSeason: TeamCaseOut = {
  ...evidence,
  wins: 8,
  losses: 8,
  ties: 1,
  games: [...evidence.games, tiedGame],
}

describe('TeamCaseReceipts', () => {
  it('renders the win-loss record', () => {
    render(<TeamCaseReceipts evidence={evidence} />)

    expect(screen.getByText(/13-0/)).toBeInTheDocument()
  })

  it('keeps a tie-free record as plain W-L (no trailing "-0"), so CFB display is unchanged', () => {
    render(<TeamCaseReceipts evidence={{ ...evidence, ties: 0 }} />)

    expect(screen.getByText(/Record: 13-0 /)).toBeInTheDocument()
    expect(screen.queryByText(/13-0-0/)).not.toBeInTheDocument()
  })

  it('renders a W-L-T record when the team has ties', () => {
    render(<TeamCaseReceipts evidence={tiedSeason} />)

    expect(screen.getByText(/Record: 8-8-1 /)).toBeInTheDocument()
  })

  it('renders a tied game with its own tie tag -- visible "T", read as "Tie", not styled as a loss', () => {
    render(<TeamCaseReceipts evidence={tiedSeason} />)

    const schedule = screen.getByRole('list', { name: /full schedule/i })
    const tiedRow = within(schedule)
      .getByText(/Minnesota Vikings/)
      .closest('li') as HTMLElement
    const tag = resultTagIn(tiedRow)

    expect(tag.className).toMatch(/gamelineTagT/)
    expect(tag.className).not.toMatch(/gamelineTagL/)
    expect(tag.className).not.toMatch(/gamelineTagW/)
    // Visible short label, hidden from assistive tech so it isn't read as the letter...
    expect(within(tag).getByText('T')).toHaveAttribute('aria-hidden', 'true')
    // ...and a full word for screen readers.
    expect(within(tag).getByText('Tie')).toBeInTheDocument()
  })

  it('gives win and loss tags the same visible-letter / spoken-word treatment', () => {
    render(
      <TeamCaseReceipts
        evidence={{
          ...evidence,
          losses: 1,
          worst_loss: { ...baseOpponent, opponent_name: 'Baylor', result: 'L' },
        }}
      />,
    )

    const worstLoss = screen.getByRole('list', { name: /worst loss/i })
    const lossTag = resultTagIn(within(worstLoss).getByRole('listitem'))
    expect(within(lossTag).getByText('L')).toHaveAttribute(
      'aria-hidden',
      'true',
    )
    expect(within(lossTag).getByText('Loss')).toBeInTheDocument()

    const qualityWins = screen.getByRole('list', { name: /quality wins/i })
    const winTag = resultTagIn(within(qualityWins).getByRole('listitem'))
    expect(within(winTag).getByText('W')).toHaveAttribute('aria-hidden', 'true')
    expect(within(winTag).getByText('Win')).toBeInTheDocument()
  })

  it('renders the rating scaled by 1000 via formatRating, not the raw eigenvector value', () => {
    render(<TeamCaseReceipts evidence={evidence} />)

    expect(screen.getByText(/12\.34/)).toBeInTheDocument()
  })

  it('renders an Elo rating on Elo’s own scale via evidence.method, not x1000', () => {
    const { container } = render(
      <TeamCaseReceipts
        evidence={{
          ...evidence,
          method: 'elo',
          rating: 1684.4,
          rating_breakdown: { entries: [], residual_contribution: 0 },
        }}
      />,
    )

    expect(screen.getByText(/Rating 1,684/)).toBeInTheDocument()
    expect(container.textContent).not.toContain('1684400.00')
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

  /**
   * Issue #153: the breakdown disclosure explains Keener's math, and Elo
   * writes no breakdown rows -- so under Elo it would print "Total 0" beside
   * "Matches the displayed rating: 1,684". Whether to show it is decided by
   * the method, never by the breakdown's emptiness.
   */
  describe('rating breakdown is decided by method, not by emptiness (issue #153)', () => {
    const NO_BREAKDOWN_EXPLAINER =
      'Elo builds its rating game by game, in date order, with margin of victory counted — it has no per-opponent breakdown to show.'

    // Issue #183 retired the explainer above. With no ledger in the
    // response, each Elo method prints its own line instead.
    const NOTE_WITHOUT_LEDGER = {
      elo: "This rating's game-by-game work isn't available right now.",
      elo_career:
        "Career Elo carries ratings across seasons, and its game-by-game work isn't shown yet.",
    } as const

    // The real Elo wire shape (zero rows deserialize to this), plus a
    // non-empty one: an emptiness heuristic would show a disclosure for the
    // second, a method decision never does.
    const BREAKDOWN_SHAPES: ReadonlyArray<
      readonly [string, TeamCaseOut['rating_breakdown']]
    > = [
      [
        'empty, as the API really sends it',
        { entries: [], residual_contribution: 0 },
      ],
      ['non-empty', evidence.rating_breakdown],
    ]

    describe.each(['elo', 'elo_career'] as const)('%s', (method) => {
      it.each(BREAKDOWN_SHAPES)(
        'renders the rating as plain Elo-format text with no breakdown trigger and no Keener copy (breakdown %s)',
        (_label, rating_breakdown) => {
          const { container } = render(
            <TeamCaseReceipts
              evidence={{
                ...evidence,
                method,
                rating: 1684.4,
                rating_breakdown,
              }}
            />,
          )

          expect(container.textContent).not.toMatch(/Keener/)
          expect(container.querySelector('[aria-haspopup="dialog"]')).toBeNull()
          expect(screen.queryByRole('button')).not.toBeInTheDocument()
          expect(screen.getByText(/Rating 1,684/)).toBeInTheDocument()
          expect(
            screen.queryByText(NO_BREAKDOWN_EXPLAINER),
          ).not.toBeInTheDocument()
          expect(screen.getAllByText(NOTE_WITHOUT_LEDGER[method])).toHaveLength(
            1,
          )
        },
      )
    })

    it('keeps the disclosure for a Keener rating, with no Elo explainer', () => {
      render(<TeamCaseReceipts evidence={evidence} />)

      expect(screen.getByRole('button', { name: '12.34' })).toHaveAttribute(
        'aria-haspopup',
        'dialog',
      )
      expect(screen.queryByText(NO_BREAKDOWN_EXPLAINER)).not.toBeInTheDocument()
    })

    it('keeps the disclosure for a legitimate all-zero Keener breakdown', () => {
      render(
        <TeamCaseReceipts
          evidence={{
            ...evidence,
            rating: 0,
            rating_breakdown: { entries: [], residual_contribution: 0 },
          }}
        />,
      )

      expect(screen.getByRole('button', { name: '0.00' })).toHaveAttribute(
        'aria-haspopup',
        'dialog',
      )
      expect(screen.queryByText(NO_BREAKDOWN_EXPLAINER)).not.toBeInTheDocument()
    })
  })

  /**
   * Issue #183: under Elo the rating opens the engine's own game-by-game
   * ledger. A stale API/db that sends no ledger gets the plain rating and one
   * honest line, never an empty or invented panel; career Elo explains why
   * its work isn't shown.
   */
  describe('Elo ledger disclosure (issue #183)', () => {
    const UNAVAILABLE =
      "This rating's game-by-game work isn't available right now."
    const CAREER =
      "Career Elo carries ratings across seasons, and its game-by-game work isn't shown yet."
    const OLD_EXPLAINER =
      'Elo builds its rating game by game, in date order, with margin of victory counted — it has no per-opponent breakdown to show.'

    const texasElo: TeamCaseOut = {
      ...evidence,
      method: 'elo',
      team_name: TEXAS_ELO.team_name,
      rating: TEXAS_ELO.rating,
      wins: TEXAS_ELO.wins,
      losses: TEXAS_ELO.losses,
      ties: TEXAS_ELO.ties,
      rating_breakdown: { entries: [], residual_contribution: 0 },
      elo_ledger: TEXAS_ELO.elo_ledger,
    }

    it('elo: the rating is a trigger that opens the team’s ledger, with no old explainer or Keener copy', async () => {
      const user = userEvent.setup()
      const { container } = render(<TeamCaseReceipts evidence={texasElo} />)

      const trigger = screen.getByRole('button', { name: '1,661' })
      expect(trigger).toHaveAttribute('aria-haspopup', 'dialog')
      expect(screen.queryByText(OLD_EXPLAINER)).not.toBeInTheDocument()
      expect(screen.queryByText(UNAVAILABLE)).not.toBeInTheDocument()
      expect(screen.queryByText(CAREER)).not.toBeInTheDocument()

      await user.hover(trigger)
      const dialog = screen.getByRole('dialog', {
        name: 'Texas Elo rating, game by game',
      })
      expect(
        within(
          within(dialog).getByRole('list', { name: 'Games, in order' }),
        ).getAllByRole('listitem'),
      ).toHaveLength(5)
      expect(
        within(dialog).queryByText(/rating-system baseline/i),
      ).not.toBeInTheDocument()
      expect(container.textContent).not.toMatch(/Keener/)
    })

    it('(e) elo with a null ledger: the plain rating and the unavailable line, no trigger', () => {
      render(<TeamCaseReceipts evidence={{ ...texasElo, elo_ledger: null }} />)

      expect(screen.queryByRole('button')).not.toBeInTheDocument()
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
      expect(screen.getByText(/Rating 1,661/)).toBeInTheDocument()
      expect(screen.getAllByText(UNAVAILABLE)).toHaveLength(1)
      expect(screen.queryByText(OLD_EXPLAINER)).not.toBeInTheDocument()
    })

    it('(g) elo_career: the career explainer and no trigger, even if a ledger were sent', () => {
      for (const elo_ledger of [null, TEXAS_ELO.elo_ledger]) {
        const { unmount } = render(
          <TeamCaseReceipts
            evidence={{ ...texasElo, method: 'elo_career', elo_ledger }}
          />,
        )

        expect(screen.queryByRole('button')).not.toBeInTheDocument()
        expect(screen.getByText(/Rating 1,661/)).toBeInTheDocument()
        expect(screen.getAllByText(CAREER)).toHaveLength(1)
        expect(screen.queryByText(UNAVAILABLE)).not.toBeInTheDocument()
        unmount()
      }
    })

    it('keener: still the Keener breakdown, with no Elo ledger copy', async () => {
      const user = userEvent.setup()
      render(<TeamCaseReceipts evidence={evidence} />)

      await user.hover(screen.getByRole('button', { name: '12.34' }))
      const dialog = screen.getByRole('dialog', {
        name: 'Texas rating breakdown',
      })
      expect(within(dialog).queryByText(/game by game/)).not.toBeInTheDocument()
      expect(screen.queryByText(UNAVAILABLE)).not.toBeInTheDocument()
      expect(screen.queryByText(CAREER)).not.toBeInTheDocument()
    })
  })
})
