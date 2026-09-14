import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { METHODS, type ComparisonResultOut } from '../../lib/api/types'
import { formatRating } from '../../lib/formatRating'
import { ComparisonReceipts } from './ComparisonReceipts'
import { TEXAS_ELO, USC_ELO } from './eloLedgerFixture'

/**
 * A distinctive stand-in for the engine's raw `verdict` sentence. apps/web
 * deliberately never renders `verdict` (issue #24), so this must never appear.
 */
const VERDICT_SENTINEL = 'ENGINE-VERDICT-SENTINEL-must-not-render'

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
    elo_ledger: null,
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
    ties: 0,
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
    elo_ledger: null,
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
  verdict: VERDICT_SENTINEL,
}

/** Swaps in both teams' names, ranks and ratings, keeping `rating_diff` consistent with them. */
function withRatings(
  base: ComparisonResultOut,
  method: ComparisonResultOut['method'],
  a: { team_name: string; rank: number; rating: number },
  b: { team_name: string; rank: number; rating: number },
): ComparisonResultOut {
  return {
    ...base,
    method,
    team_a: { ...base.team_a, ...a },
    team_b: { ...base.team_b, ...b },
    rating_diff: a.rating - b.rating,
  }
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

  describe('verdict line (issues #24, #82)', () => {
    it('never renders the engine’s raw verdict sentence', () => {
      const { container } = render(<ComparisonReceipts evidence={evidence} />)

      expect(container.textContent).not.toContain(VERDICT_SENTINEL)
    })

    it('Keener: names team_a as the leader when rating_diff > 0, with display-scaled numbers ordered a-then-b', () => {
      render(<ComparisonReceipts evidence={evidence} />)

      expect(
        screen.getByText(
          'Rating diff: 2.75 · Ohio State rates higher overall (8.77 vs 6.02, rank 2 vs 95).',
        ),
      ).toBeInTheDocument()
    })

    it('Keener: names team_b as the leader when rating_diff < 0, keeping numbers ordered a-then-b', () => {
      render(
        <ComparisonReceipts
          evidence={withRatings(
            evidence,
            'keener',
            { team_name: 'Ohio State', rank: 40, rating: 0.00602 },
            { team_name: 'Michigan', rank: 2, rating: 0.00877 },
          )}
        />,
      )

      expect(
        screen.getByText(
          'Rating diff: -2.75 · Michigan rates higher overall (6.02 vs 8.77, rank 40 vs 2).',
        ),
      ).toBeInTheDocument()
    })

    it('Elo: formats the leader line and the rating diff on Elo’s own scale', () => {
      const { container } = render(
        <ComparisonReceipts
          evidence={withRatings(
            evidence,
            'elo',
            { team_name: 'Ohio State', rank: 3, rating: 1684.4 },
            { team_name: 'Michigan', rank: 9, rating: 1650.2 },
          )}
        />,
      )

      expect(
        screen.getByText(
          'Rating diff: 34 · Ohio State rates higher overall (1,684 vs 1,650, rank 3 vs 9).',
        ),
      ).toBeInTheDocument()
      expect(container.textContent).not.toContain('1684400.00')
    })

    it('Keener: says the teams rate the same, naming no leader, when both ratings print identically', () => {
      // 2013 Texas vs Texas Tech (#149): both print "3.50" despite a real raw
      // difference.
      render(
        <ComparisonReceipts
          evidence={withRatings(
            evidence,
            'keener',
            { team_name: 'Texas', rank: 40, rating: 0.0035021 },
            { team_name: 'Texas Tech', rank: 41, rating: 0.0035018 },
          )}
        />,
      )

      expect(
        screen.getByText(
          'Rating diff: 0.00 · Texas and Texas Tech rate the same at display precision (3.50; rank 40 vs 41).',
        ),
      ).toBeInTheDocument()
      expect(screen.queryByText(/rates higher/)).not.toBeInTheDocument()
    })

    it('Elo: says the teams rate the same, naming no leader, when both ratings print identically', () => {
      // Differ by under one Elo point: both print "1,531".
      render(
        <ComparisonReceipts
          evidence={withRatings(
            evidence,
            'elo',
            { team_name: 'UNLV', rank: 60, rating: 1531.24 },
            { team_name: 'Nevada', rank: 61, rating: 1530.9 },
          )}
        />,
      )

      expect(
        screen.getByText(
          'Rating diff: 0 · UNLV and Nevada rate the same at display precision (1,531; rank 60 vs 61).',
        ),
      ).toBeInTheDocument()
      expect(screen.queryByText(/rates higher/)).not.toBeInTheDocument()
    })

    it('says the teams rate the same on an exact tie (rating_diff === 0)', () => {
      // UNLV's real Elo value from #149's validator run, on both sides.
      const tie = withRatings(
        evidence,
        'elo',
        { team_name: 'UNLV', rank: 60, rating: 1531.2 },
        { team_name: 'Nevada', rank: 61, rating: 1531.2 },
      )
      expect(tie.rating_diff).toBe(0)

      render(<ComparisonReceipts evidence={tie} />)

      expect(
        screen.getByText(
          'Rating diff: 0 · UNLV and Nevada rate the same at display precision (1,531; rank 60 vs 61).',
        ),
      ).toBeInTheDocument()
      expect(screen.queryByText(/rates higher/)).not.toBeInTheDocument()
    })

    describe('diff, printed ratings and wording always agree (reviewer follow-up)', () => {
      it('(a) Elo 1531.5 vs 1531.4: prints diff 1 beside the leader, not 0', () => {
        // 1531.5 -> 1,532 and 1531.4 -> 1,531, so the printed diff is
        // 1532 - 1531 = 1 and A (the larger printed number) leads. The raw
        // diff 0.1 would have printed "0".
        render(
          <ComparisonReceipts
            evidence={withRatings(
              evidence,
              'elo',
              { team_name: 'Boise State', rank: 20, rating: 1531.5 },
              { team_name: 'Fresno State', rank: 21, rating: 1531.4 },
            )}
          />,
        )

        expect(
          screen.getByText(
            'Rating diff: 1 · Boise State rates higher overall (1,532 vs 1,531, rank 20 vs 21).',
          ),
        ).toBeInTheDocument()
      })

      it('(b) Elo 1531.49 vs 1530.5: both print 1,531, so diff 0 and "rate the same"', () => {
        // 1531.49 -> 1,531 and 1530.5 -> 1,531 (Math.round takes .5 up): the
        // printed numbers are equal, so the diff is 0 and no leader is named.
        // The raw diff 0.99 would have printed "1".
        render(
          <ComparisonReceipts
            evidence={withRatings(
              evidence,
              'elo',
              { team_name: 'UNLV', rank: 60, rating: 1531.49 },
              { team_name: 'Nevada', rank: 61, rating: 1530.5 },
            )}
          />,
        )

        expect(
          screen.getByText(
            'Rating diff: 0 · UNLV and Nevada rate the same at display precision (1,531; rank 60 vs 61).',
          ),
        ).toBeInTheDocument()
      })

      it('(c) Keener 0.0034951 vs 0.0035049: both print 3.50, so diff 0.00 and "rate the same"', () => {
        // x1000 to 2 dp: 3.4951 -> 3.50 and 3.5049 -> 3.50, equal, so the diff
        // is 3.50 - 3.50 = 0.00. The raw diff -0.0000098 would have printed
        // "-0.01".
        render(
          <ComparisonReceipts
            evidence={withRatings(
              evidence,
              'keener',
              { team_name: 'Texas', rank: 40, rating: 0.0034951 },
              { team_name: 'Texas Tech', rank: 41, rating: 0.0035049 },
            )}
          />,
        )

        expect(
          screen.getByText(
            'Rating diff: 0.00 · Texas and Texas Tech rate the same at display precision (3.50; rank 40 vs 41).',
          ),
        ).toBeInTheDocument()
      })

      it('derives the whole line from the two ratings, never from the raw rating_diff', () => {
        const consistent = withRatings(
          evidence,
          'elo',
          { team_name: 'Boise State', rank: 20, rating: 1531.5 },
          { team_name: 'Fresno State', rank: 21, rating: 1531.4 },
        )
        const { container, unmount } = render(
          <ComparisonReceipts evidence={consistent} />,
        )
        const expected = container.textContent
        unmount()

        // A stale or mis-signed rating_diff must not change a single character.
        for (const rating_diff of [0, -0.1, 999, -999]) {
          const { container: other, unmount: unmountOther } = render(
            <ComparisonReceipts evidence={{ ...consistent, rating_diff }} />,
          )
          expect({ rating_diff, text: other.textContent }).toEqual({
            rating_diff,
            text: expected,
          })
          unmountOther()
        }
      })

      /** Rating pairs per method: the reviewer's cases, #149's near-ties, .5 straddles, both orderings, clear leaders, exact ties. */
      const GRID: Record<
        ComparisonResultOut['method'],
        ReadonlyArray<readonly [number, number]>
      > = {
        keener: [
          [0.0034951, 0.0035049],
          [0.0035049, 0.0034951],
          [0.0035021, 0.0035018],
          [0.0035018, 0.0035021],
          [0.003505, 0.003495],
          [0.003495, 0.003505],
          [0.0035, 0.00349],
          [0.00349, 0.0035],
          [0.0034949, 0.003495],
          [0.00877, 0.00602],
          [0.00602, 0.00877],
          [0.0035021, 0.0035021],
          [0, 0.0000049],
        ],
        elo: [
          [1531.5, 1531.4],
          [1531.4, 1531.5],
          [1531.49, 1530.5],
          [1530.5, 1531.49],
          [1531.24, 1530.9],
          [1530.9, 1531.24],
          [1531.5, 1530.5],
          [1530.5, 1531.5],
          [1531.2, 1531.2],
          [1684.4, 1650.2],
          [1650.2, 1684.4],
          [-12.5, -13.5],
          [-13.5, -12.5],
          [0.4, -0.4],
        ],
        elo_career: [
          [1531.5, 1531.4],
          [1531.49, 1530.5],
          [1530.5, 1531.49],
          [999.5, 1000.49],
          [1000.5, 999.5],
          [1801.7, 1488.3],
          [1488.3, 1801.7],
          [1600, 1600],
        ],
      }

      const LINE =
        /^Rating diff: (?<diff>\S+) · (?:(?<leader>.+) rates higher overall \((?<fa>\S+) vs (?<fb>\S+), rank \d+ vs \d+\)\.|A-team and B-team rate the same at display precision \((?<same>\S+); rank \d+ vs \d+\)\.)$/

      const toNumber = (printed: string): number =>
        Number(printed.replace(/,/g, ''))

      it.each(METHODS)(
        '%s: invariants 1-3 hold across the rating-pair grid',
        (method) => {
          const pairs = GRID[method]
          expect(pairs.length).toBeGreaterThan(0)

          for (const [ra, rb] of pairs) {
            const { container, unmount } = render(
              <ComparisonReceipts
                evidence={withRatings(
                  evidence,
                  method,
                  { team_name: 'A-team', rank: 1, rating: ra },
                  { team_name: 'B-team', rank: 2, rating: rb },
                )}
              />,
            )
            const text =
              within(container).getByText(/^Rating diff:/).textContent
            unmount()
            const context = { method, ra, rb, text }

            const match = LINE.exec(text ?? '')
            expect(match, JSON.stringify(context)).not.toBeNull()
            const g = match?.groups ?? {}
            const diff = g.diff ?? ''
            const same = g.same !== undefined
            const fa = same ? (g.same ?? '') : (g.fa ?? '')
            const fb = same ? (g.same ?? '') : (g.fb ?? '')

            // The printed ratings are the ones the team summaries print.
            expect([fa, fb], JSON.stringify(context)).toEqual([
              formatRating(ra, method),
              formatRating(rb, method),
            ])

            // 1. The diff is the printed a minus printed b, on the method's
            // display format, and never a signed zero.
            const decimals = method === 'keener' ? 2 : 0
            const diffShape =
              decimals === 0 ? /^-?\d{1,3}(,\d{3})*$/ : /^-?\d+\.\d{2}$/
            expect(diff, JSON.stringify(context)).toMatch(diffShape)
            expect(diff, JSON.stringify(context)).not.toMatch(/^-0(\.0+)?$/)
            expect(
              Math.abs(toNumber(diff) - (toNumber(fa) - toNumber(fb))),
              JSON.stringify(context),
            ).toBeLessThan(10 ** -(decimals + 3))

            // 2. "Same" wording <=> equal printed ratings <=> zero diff.
            const zero = decimals === 0 ? '0' : '0.00'
            expect(
              {
                sameWording: same,
                equalPrinted: fa === fb,
                zeroDiff: diff === zero,
              },
              JSON.stringify(context),
            ).toEqual({ sameWording: same, equalPrinted: same, zeroDiff: same })

            // 3. A named leader has the strictly larger printed number.
            if (!same) {
              const aLarger = toNumber(fa) > toNumber(fb)
              expect(g.leader, JSON.stringify(context)).toBe(
                aLarger ? 'A-team' : 'B-team',
              )
            }
          }
        },
      )
    })
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

  it('renders a W-L-T record for a team with ties, and plain W-L for a team without', () => {
    render(
      <ComparisonReceipts
        evidence={{
          ...evidence,
          team_a: { ...evidence.team_a, wins: 6, losses: 9, ties: 1 },
          team_b: { ...evidence.team_b, ties: 0 },
        }}
      />,
    )

    expect(screen.getByText('6-9-1')).toBeInTheDocument()
    expect(screen.getByText('2-4')).toBeInTheDocument()
  })

  it('renders a tied common-opponent result with its own tie tag (visible "T", read as "Tie"), not loss styling', () => {
    render(
      <ComparisonReceipts
        evidence={{
          ...evidence,
          team_a: { ...evidence.team_a, ties: 1 },
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
          ],
        }}
      />,
    )

    const row = screen.getByText(/Indiana/).closest('li') as HTMLElement
    const [tagA, tagB] = Array.from(
      row.querySelectorAll<HTMLElement>('[class*="gamelineTag"]'),
    )
    if (tagA === undefined || tagB === undefined) {
      throw new Error('expected one result tag per team in the row')
    }

    expect(tagA.className).toMatch(/gamelineTagT/)
    expect(tagA.className).not.toMatch(/gamelineTagL/)
    expect(within(tagA).getByText('T')).toHaveAttribute('aria-hidden', 'true')
    expect(within(tagA).getByText('Tie')).toBeInTheDocument()

    // Team B's side of the same opponent is still an ordinary loss.
    expect(tagB.className).toMatch(/gamelineTagL/)
    expect(within(tagB).getByText('Loss')).toBeInTheDocument()
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

  /**
   * Issue #153: the breakdown disclosure explains Keener's math, and Elo
   * writes no breakdown rows. Whether to show it is decided by the method,
   * never by the breakdown's emptiness.
   */
  describe('rating breakdown is decided by method, not by emptiness (issue #153)', () => {
    const NO_BREAKDOWN_EXPLAINER =
      'Elo builds its rating game by game, in date order, with margin of victory counted — it has no per-opponent breakdown to show.'

    const EMPTY = { entries: [], residual_contribution: 0 }

    // Issue #183 retired the explainer above. With no ledger in the response,
    // Elo says so once per team; career Elo explains once per receipts block.
    const NOTE_WITHOUT_LEDGER = {
      elo: {
        text: "This rating's game-by-game work isn't available right now.",
        count: 2,
      },
      elo_career: {
        text: "Career Elo carries ratings across seasons, and its game-by-game work isn't shown yet.",
        count: 1,
      },
    } as const

    /** Both teams on `method`, with the given breakdowns. */
    function eloComparison(
      method: ComparisonResultOut['method'],
      breakdowns: 'empty' | 'non-empty',
    ): ComparisonResultOut {
      const base = withRatings(
        evidence,
        method,
        { team_name: 'Ohio State', rank: 3, rating: 1684.4 },
        { team_name: 'Michigan', rank: 9, rating: 1650.2 },
      )
      return breakdowns === 'empty'
        ? {
            ...base,
            team_a: { ...base.team_a, rating_breakdown: EMPTY },
            team_b: { ...base.team_b, rating_breakdown: EMPTY },
          }
        : base
    }

    describe.each(['elo', 'elo_career'] as const)('%s', (method) => {
      it.each(['empty', 'non-empty'] as const)(
        'renders both ratings as plain Elo-format text, no breakdown trigger, no Keener copy, one explainer (breakdowns %s)',
        (breakdowns) => {
          const { container } = render(
            <ComparisonReceipts evidence={eloComparison(method, breakdowns)} />,
          )

          expect(container.textContent).not.toMatch(/Keener/)
          expect(container.querySelector('[aria-haspopup="dialog"]')).toBeNull()
          expect(screen.queryByRole('button')).not.toBeInTheDocument()
          expect(screen.getByText('1,684')).toBeInTheDocument()
          expect(screen.getByText('1,650')).toBeInTheDocument()
          expect(
            screen.queryByText(NO_BREAKDOWN_EXPLAINER),
          ).not.toBeInTheDocument()
          expect(
            screen.getAllByText(NOTE_WITHOUT_LEDGER[method].text),
          ).toHaveLength(NOTE_WITHOUT_LEDGER[method].count)
        },
      )
    })

    it('keeps both disclosures for Keener ratings, with no Elo explainer', () => {
      render(<ComparisonReceipts evidence={evidence} />)

      for (const name of ['8.77', '6.02']) {
        expect(screen.getByRole('button', { name })).toHaveAttribute(
          'aria-haspopup',
          'dialog',
        )
      }
      expect(screen.queryByText(NO_BREAKDOWN_EXPLAINER)).not.toBeInTheDocument()
    })

    it('keeps the disclosures for legitimate all-zero Keener breakdowns', () => {
      render(
        <ComparisonReceipts
          evidence={{
            ...evidence,
            team_a: { ...evidence.team_a, rating: 0, rating_breakdown: EMPTY },
            team_b: { ...evidence.team_b, rating: 0, rating_breakdown: EMPTY },
            rating_diff: 0,
          }}
        />,
      )

      const triggers = screen.getAllByRole('button', { name: '0.00' })
      expect(triggers).toHaveLength(2)
      for (const trigger of triggers) {
        expect(trigger).toHaveAttribute('aria-haspopup', 'dialog')
      }
      expect(screen.queryByText(NO_BREAKDOWN_EXPLAINER)).not.toBeInTheDocument()
    })
  })

  /** Issue #183: under Elo each team's rating opens that team's own ledger. */
  describe('Elo ledger disclosure (issue #183)', () => {
    const UNAVAILABLE =
      "This rating's game-by-game work isn't available right now."
    const CAREER =
      "Career Elo carries ratings across seasons, and its game-by-game work isn't shown yet."
    const OLD_EXPLAINER =
      'Elo builds its rating game by game, in date order, with margin of victory counted — it has no per-opponent breakdown to show.'

    function texasVsUsc(
      method: ComparisonResultOut['method'],
    ): ComparisonResultOut {
      const base = withRatings(
        evidence,
        method,
        { team_name: 'Texas', rank: 1, rating: TEXAS_ELO.rating },
        { team_name: 'USC', rank: 2, rating: USC_ELO.rating },
      )
      return {
        ...base,
        team_a: { ...base.team_a, elo_ledger: TEXAS_ELO.elo_ledger },
        team_b: { ...base.team_b, elo_ledger: USC_ELO.elo_ledger },
      }
    }

    it('(f) elo: each team has its own ledger trigger, and the old explainer is gone', async () => {
      const user = userEvent.setup()
      render(<ComparisonReceipts evidence={texasVsUsc('elo')} />)

      expect(screen.getAllByRole('button')).toHaveLength(2)
      expect(screen.queryByText(OLD_EXPLAINER)).not.toBeInTheDocument()
      expect(screen.queryByText(UNAVAILABLE)).not.toBeInTheDocument()
      expect(screen.queryByText(CAREER)).not.toBeInTheDocument()

      for (const [label, team, games] of [
        ['1,661', 'Texas', 5],
        ['1,527', 'USC', 2],
      ] as const) {
        const trigger = screen.getByRole('button', { name: label })
        await user.hover(trigger)
        const dialog = screen.getByRole('dialog', {
          name: `${team} Elo rating, game by game`,
        })
        expect(
          within(
            within(dialog).getByRole('list', { name: 'Games, in order' }),
          ).getAllByRole('listitem'),
        ).toHaveLength(games)
        expect(
          within(dialog).getByText(`The card rounds this to ${label}.`),
        ).toBeInTheDocument()
        await user.unhover(trigger)
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
      }
    })

    it('(f) elo: one team with a null ledger gets the plain rating and the unavailable line; the other keeps its trigger', () => {
      const both = texasVsUsc('elo')
      render(
        <ComparisonReceipts
          evidence={{ ...both, team_b: { ...both.team_b, elo_ledger: null } }}
        />,
      )

      expect(screen.getAllByRole('button')).toHaveLength(1)
      expect(screen.getByRole('button', { name: '1,661' })).toBeInTheDocument()
      expect(screen.getByText('1,527')).toBeInTheDocument()
      expect(screen.getAllByText(UNAVAILABLE)).toHaveLength(1)
    })

    it('(f) keener: nothing changes -- Keener disclosures, no Elo copy', async () => {
      const user = userEvent.setup()
      render(<ComparisonReceipts evidence={evidence} />)

      await user.hover(screen.getByRole('button', { name: '8.77' }))
      const dialog = screen.getByRole('dialog', {
        name: 'Ohio State rating breakdown',
      })
      expect(
        within(dialog).getByText(/rating-system baseline/i),
      ).toBeInTheDocument()
      expect(screen.queryByText(/game by game/)).not.toBeInTheDocument()
      expect(screen.queryByText(UNAVAILABLE)).not.toBeInTheDocument()
      expect(screen.queryByText(CAREER)).not.toBeInTheDocument()
    })

    it('(g) elo_career: one career explainer, no triggers, even if ledgers were sent', () => {
      render(<ComparisonReceipts evidence={texasVsUsc('elo_career')} />)

      expect(screen.queryByRole('button')).not.toBeInTheDocument()
      expect(screen.getAllByText(CAREER)).toHaveLength(1)
      expect(screen.queryByText(UNAVAILABLE)).not.toBeInTheDocument()
    })
  })
})
