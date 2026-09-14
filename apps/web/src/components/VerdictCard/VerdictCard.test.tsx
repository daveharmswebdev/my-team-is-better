import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { NETWORK_ERROR_COPY } from '../../lib/api/client'
import type { ComparisonEnvelope, TeamCaseEnvelope } from '../../lib/api/types'
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
    // apps/web renders its own formatted verdict line, never the engine's
    // raw `verdict` sentence (issue #24).
    expect(
      screen.getByText(
        'Rating diff: 0.87 · Texas rates higher overall (12.34 vs 11.47, rank 1 vs 2).',
      ),
    ).toBeInTheDocument()
    expect(screen.queryByText(/Texas was better\./)).not.toBeInTheDocument()
  })

  /** Issue #184: a verdict can be shared by link, from the foot of the card. */
  describe('the share button', () => {
    const SHARE_URL =
      'https://my-team-is-better.lol/?q=champion&sport=cfb&year=2005&engine=keener'

    it.each([
      ['team-case', teamCaseEnvelope],
      ['compare', comparisonEnvelope],
    ] as const)(
      'renders "Share this verdict" at the foot of a %s success card when shareUrl is set',
      (_kind, envelope) => {
        render(
          <VerdictCard
            state={{ status: 'success', envelope }}
            shareUrl={SHARE_URL}
          />,
        )

        const button = screen.getByRole('button', {
          name: 'Share this verdict',
        })
        const article = screen.getByRole('article')
        expect(article).toContainElement(button)
        expect(article.lastElementChild).toContainElement(button)
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
})
