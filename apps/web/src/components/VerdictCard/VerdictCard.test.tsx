import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { composeStories } from '@storybook/react-vite'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { NETWORK_ERROR_COPY } from '../../lib/api/client'
import type { ComparisonEnvelope, TeamCaseEnvelope } from '../../lib/api/types'
import { expectReadingOrder, matchMediaFor } from '../../test/viewport'
import * as stories from './VerdictCard.stories'
import { VerdictCard } from './VerdictCard'

const teamCaseEnvelope: TeamCaseEnvelope = {
  evidence: {
    year: 2005,
    method: 'keener',
    team_id: 1,
    team_name: 'Texas',
    rank: 1,
    rating: 0.01234,
    wins: 13,
    losses: 0,
    ties: 0,
    rating_breakdown: { entries: [], residual_contribution: 0.01234 },
    elo_ledger: null,
    games: [],
    quality_wins: [],
    worst_loss: null,
  },
  narration: {
    text: 'Texas was the best team in 2005, full stop.',
    contested: false,
    cached: false,
  },
  other_method_ranks: [],
}

const comparisonEnvelope: ComparisonEnvelope = {
  evidence: {
    year: 2005,
    method: 'keener',
    team_a: {
      team_id: 1,
      team_name: 'Texas',
      rank: 1,
      rating: 0.01234,
      wins: 13,
      losses: 0,
      ties: 0,
      rating_breakdown: { entries: [], residual_contribution: 0.01234 },
      elo_ledger: null,
      quality_wins: [],
      worst_loss: null,
    },
    team_b: {
      team_id: 2,
      team_name: 'USC',
      rank: 2,
      rating: 0.01147,
      wins: 12,
      losses: 1,
      ties: 0,
      rating_breakdown: { entries: [], residual_contribution: 0.01147 },
      elo_ledger: null,
      quality_wins: [],
      worst_loss: null,
    },
    head_to_head: { played: false, meetings: [] },
    common_opponents: [],
    rating_diff: 0.00087,
    verdict: 'Texas was better.',
  },
  narration: { text: 'Texas edges USC.', contested: true, cached: true },
  team_a_other_method_ranks: [],
  team_b_other_method_ranks: [],
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
    expect(
      within(screen.getByRole('region', { name: 'Texas evidence' })).getByText(
        /13-0/,
      ),
    ).toBeInTheDocument()
  })

  it('renders the narration and comparison receipts on success', () => {
    render(
      <VerdictCard
        state={{ status: 'success', envelope: comparisonEnvelope }}
      />,
    )

    expect(screen.getByText('Texas edges USC.')).toBeInTheDocument()
    // apps/web renders its own formatted verdict line, never the engine's
    // raw `verdict` sentence (issue #24).
    expect(
      screen.getByText(
        'Rating diff: 0.87 · Texas rates higher overall (12.34 vs 11.47, rank 1 vs 2).',
      ),
    ).toBeInTheDocument()
    expect(screen.queryByText(/Texas was better\./)).not.toBeInTheDocument()
  })

  /**
   * Issue #474: the card opens on who's compared -- name, rank and record --
   * then the verdict, then the other engines' ranks, then the receipts.
   */
  describe('the teams header', () => {
    it('names both teams of a comparison with rank and record, before the verdict', () => {
      render(
        <VerdictCard
          state={{
            status: 'success',
            envelope: {
              ...comparisonEnvelope,
              team_a_other_method_ranks: [{ method: 'elo', rank: 1 }],
            },
          }}
        />,
      )

      const header = screen.getByRole('list', { name: 'Teams compared' })
      const items = within(header).getAllByRole('listitem')
      expect(items.map((item) => item.textContent)).toEqual([
        'Texas Rank #1 · 13-0',
        'USC Rank #2 · 12-1',
      ])
      expectReadingOrder(
        header,
        screen.getByText('Texas edges USC.'),
        screen.getByText(/^Engine: /),
        screen.getByText('Texas · Elo (second opinion): #1'),
        screen.getByRole('region', { name: 'comparison evidence' }),
      )
    })

    it('names the one team of a team case with rank and record, before the verdict', () => {
      render(
        <VerdictCard
          state={{
            status: 'success',
            envelope: {
              ...teamCaseEnvelope,
              evidence: { ...teamCaseEnvelope.evidence, ties: 1 },
              other_method_ranks: [{ method: 'elo', rank: 2 }],
            },
          }}
        />,
      )

      const header = screen.getByTestId('verdict-teams')
      expect(header).toHaveTextContent('Texas Rank #1 · 13-0-1')
      expect(
        screen.queryByRole('list', { name: 'Teams compared' }),
      ).not.toBeInTheDocument()
      expectReadingOrder(
        header,
        screen.getByText('Texas was the best team in 2005, full stop.'),
        screen.getByText(/^Engine: /),
        screen.getByText('Elo (second opinion): #2'),
        screen.getByRole('region', { name: 'Texas evidence' }),
      )
    })

    it('has no header outside a verdict', () => {
      render(<VerdictCard state={{ status: 'loading' }} />)
      expect(screen.queryByTestId('verdict-teams')).not.toBeInTheDocument()
    })
  })

  /** Issue #184: a verdict can be shared by link (#474: placed by viewport). */
  describe('the share button', () => {
    const SHARE_URL =
      'https://my-team-is-better.lol/?q=champion&sport=cfb&year=2005&engine=keener'

    afterEach(() => {
      vi.unstubAllGlobals()
    })

    /**
     * Issue #474: on a desktop, Share is the card's first control -- before
     * the teams and the verdict -- and there is no floating one.
     */
    it.each([
      ['team-case', teamCaseEnvelope],
      ['compare', comparisonEnvelope],
    ] as const)(
      'renders one "Share this verdict" button at the top of a %s card on a desktop',
      (_kind, envelope) => {
        vi.stubGlobal('matchMedia', matchMediaFor('desktop'))
        render(
          <VerdictCard
            state={{ status: 'success', envelope }}
            shareUrl={SHARE_URL}
          />,
        )

        const buttons = screen.getAllByRole('button', { name: /^Share/ })
        expect(buttons).toHaveLength(1)
        const [button] = buttons
        const article = screen.getByRole('article')
        expect(article.firstElementChild).toContainElement(button ?? null)
        expect(
          article.querySelector('[data-layout="inline"]'),
        ).toContainElement(button ?? null)
        expectReadingOrder(
          button as Element,
          screen.getByTestId('verdict-teams'),
          screen.getByText(envelope.narration.text),
        )
      },
    )

    /**
     * Issue #474: on a phone, Share floats bottom-right (a FAB), so it leaves
     * the content flow: last in reading order, after the receipts, and the
     * only Share button on the card.
     */
    it.each([
      ['team-case', teamCaseEnvelope],
      ['compare', comparisonEnvelope],
    ] as const)(
      'renders one floating "Share this verdict" button after the receipts of a %s card on a phone',
      (_kind, envelope) => {
        vi.stubGlobal('matchMedia', matchMediaFor('phone'))
        render(
          <VerdictCard
            state={{ status: 'success', envelope }}
            shareUrl={SHARE_URL}
          />,
        )

        const buttons = screen.getAllByRole('button', { name: /^Share/ })
        expect(buttons).toHaveLength(1)
        const [button] = buttons
        const article = screen.getByRole('article')
        expect(article.lastElementChild).toContainElement(button ?? null)
        expect(
          article.querySelector('[data-layout="floating"]'),
        ).toContainElement(button ?? null)
        expectReadingOrder(
          screen.getByTestId('verdict-teams'),
          screen.getByText(envelope.narration.text),
          screen.getByRole('region', { name: /evidence/ }),
          button as Element,
        )
      },
    )

    it('renders no share button on a success card without shareUrl', () => {
      render(
        <VerdictCard
          state={{ status: 'success', envelope: teamCaseEnvelope }}
        />,
      )

      expect(
        screen.queryByRole('button', { name: 'Share this verdict' }),
      ).not.toBeInTheDocument()
    })

    it.each([
      ['loading', { status: 'loading' }],
      [
        'error',
        {
          status: 'error',
          error: { kind: 'network_error', message: NETWORK_ERROR_COPY },
        },
      ],
    ] as const)(
      'renders no share button in the %s state, even with shareUrl',
      (_kind, state) => {
        render(<VerdictCard state={state} shareUrl={SHARE_URL} />)

        expect(
          screen.queryByRole('button', { name: 'Share this verdict' }),
        ).not.toBeInTheDocument()
      },
    )
  })

  /**
   * Issue #154: the card names the engine that actually answered, read off the
   * response envelope -- never off the form, whose toggle may already have
   * moved on to the next question.
   */
  describe('labels the answering engine from the envelope', () => {
    const cases = [
      ['team-case', 'keener', 'Engine: Keener (default)'],
      ['team-case', 'elo', 'Engine: Elo (second opinion)'],
      ['compare', 'keener', 'Engine: Keener (default)'],
      ['compare', 'elo', 'Engine: Elo (second opinion)'],
    ] as const

    it.each(cases)('%s answered by %s shows "%s"', (kind, method, label) => {
      const envelope =
        kind === 'team-case'
          ? {
              ...teamCaseEnvelope,
              evidence: { ...teamCaseEnvelope.evidence, method },
            }
          : {
              ...comparisonEnvelope,
              evidence: { ...comparisonEnvelope.evidence, method },
            }

      const { container } = render(
        <VerdictCard state={{ status: 'success', envelope }} />,
      )

      expect(screen.getByText(label)).toBeInTheDocument()
      expect(screen.getAllByText(/^Engine: /)).toHaveLength(1)
      if (method === 'elo') {
        expect(container.textContent).not.toMatch(/Keener/)
      }
    })
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

  it('renders the unknown_team error state as a not-found state with no pick list', () => {
    render(
      <VerdictCard
        state={{
          status: 'error',
          error: {
            kind: 'unknown_team',
            body: {
              error: 'unknown_team',
              query: 'Abilene Christian',
              year: 2010,
              sport: 'cfb',
            },
          },
        }}
      />,
    )

    const alert = screen.getByRole('alert')
    expect(alert).toHaveTextContent(/Abilene Christian/)
    expect(alert).toHaveTextContent(/2010 college football/i)
    expect(screen.queryByRole('list')).not.toBeInTheDocument()
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
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
          error: { kind: 'network_error', message: NETWORK_ERROR_COPY },
        }}
      />,
    )

    expect(screen.getByRole('alert')).toHaveTextContent(NETWORK_ERROR_COPY)
  })

  it("passes headingLevel to the receipts' section headings, h2 by default (issue #219)", () => {
    const { unmount } = render(
      <VerdictCard state={{ status: 'success', envelope: teamCaseEnvelope }} />,
    )
    expect(
      screen.getByRole('heading', { level: 2, name: 'Quality wins' }),
    ).toBeInTheDocument()
    unmount()

    render(
      <VerdictCard
        state={{ status: 'success', envelope: teamCaseEnvelope }}
        headingLevel={3}
      />,
    )
    expect(
      screen.getByRole('heading', { level: 3, name: 'Quality wins' }),
    ).toBeInTheDocument()
  })

  /**
   * Issue #155: where each other displayed engine ranks the same team, with a
   * control that re-asks the question under that engine. The API sends every
   * other method with a ratings row, `elo_career` included; the card shows
   * only the ones the Engine toggle offers.
   */
  describe("the other engines' ranks", () => {
    const pennState: TeamCaseEnvelope = {
      ...teamCaseEnvelope,
      evidence: {
        ...teamCaseEnvelope.evidence,
        team_name: 'Penn State',
        rank: 3,
      },
      other_method_ranks: [
        { method: 'elo', rank: 6 },
        { method: 'elo_career', rank: 8 },
      ],
    }

    it("renders the other displayed engine's rank on a team-case verdict", () => {
      render(<VerdictCard state={{ status: 'success', envelope: pennState }} />)

      expect(screen.getByText('Elo (second opinion): #6')).toBeInTheDocument()
    })

    it('does not show elo_career', () => {
      const { container } = render(
        <VerdictCard state={{ status: 'success', envelope: pennState }} />,
      )

      expect(container.textContent).not.toMatch(/Elo, career/)
      expect(container.textContent).not.toMatch(/#8/)
    })

    it('renders no line for an empty list', () => {
      render(
        <VerdictCard
          state={{ status: 'success', envelope: teamCaseEnvelope }}
          onSelectMethod={vi.fn()}
        />,
      )

      expect(screen.queryByText(/opinion\): #/)).not.toBeInTheDocument()
      expect(
        screen.queryByRole('button', { name: /^Ask / }),
      ).not.toBeInTheDocument()
    })

    it('renders a line per team on a compare verdict', () => {
      render(
        <VerdictCard
          state={{
            status: 'success',
            envelope: {
              ...comparisonEnvelope,
              team_a_other_method_ranks: [
                { method: 'elo', rank: 1 },
                { method: 'elo_career', rank: 4 },
              ],
              team_b_other_method_ranks: [{ method: 'elo', rank: 2 }],
            },
          }}
          onSelectMethod={vi.fn()}
        />,
      )

      expect(
        screen.getByText('Texas · Elo (second opinion): #1'),
      ).toBeInTheDocument()
      expect(
        screen.getByText('USC · Elo (second opinion): #2'),
      ).toBeInTheDocument()
      expect(
        screen.getAllByRole('button', { name: 'Ask Elo (second opinion)' }),
      ).toHaveLength(1)
    })

    it('calls onSelectMethod with the other method when the control is clicked', async () => {
      const onSelectMethod = vi.fn()
      render(
        <VerdictCard
          state={{ status: 'success', envelope: pennState }}
          onSelectMethod={onSelectMethod}
        />,
      )

      await userEvent.click(
        screen.getByRole('button', { name: 'Ask Elo (second opinion)' }),
      )

      expect(onSelectMethod).toHaveBeenCalledExactlyOnceWith('elo')
    })

    /**
     * Founder framing (2026-09-13): the engines have no mandate to agree.
     * Texas 2005 (Keener #1, Elo #1) and Penn State 2005 (#3, #6) render the
     * line with the same elements and the same classes; only the rank differs.
     */
    it('renders the line identically for the Texas 2005 and Penn State 2005 stories', () => {
      const { OtherEngineRanksTexas2005, OtherEngineRanksPennState2005 } =
        composeStories(stories)

      const lineShape = (Story: () => React.JSX.Element, text: string) => {
        const { unmount } = render(<Story />)
        const line = screen.getByText(text).closest('div')
        expect(line).not.toBeNull()
        const shape = elementShape(line as Element)
        unmount()
        return shape
      }

      const texas = lineShape(
        OtherEngineRanksTexas2005,
        'Elo (second opinion): #1',
      )
      const pennState = lineShape(
        OtherEngineRanksPennState2005,
        'Elo (second opinion): #6',
      )

      expect(texas).toBe(pennState)
      // Not vacuous: the shape names the line's own classes.
      expect(texas).toMatch(/p\.[^[]+\[span\.?/)
    })
  })
})

/** An element's tags and class lists, recursively, with every text node left out. */
function elementShape(element: Element): string {
  const classes = [...element.classList].sort().join('.')
  const children = [...element.children].map(elementShape).join(',')
  return `${element.tagName.toLowerCase()}${classes ? `.${classes}` : ''}[${children}]`
}
