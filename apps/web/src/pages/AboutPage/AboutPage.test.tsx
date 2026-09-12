import { render, screen, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { VerdictNetworkError } from '../../lib/api/client'
import type { CreditsMethodologyOut, CreditsOut } from '../../lib/api/types'
import { AboutPage } from './AboutPage'

vi.mock('../../lib/api/client', async () => {
  const actual = await vi.importActual<typeof import('../../lib/api/client')>(
    '../../lib/api/client',
  )
  return {
    ...actual,
    fetchCredits: vi.fn(),
  }
})

import { fetchCredits } from '../../lib/api/client'

const mockedFetchCredits = vi.mocked(fetchCredits)

/**
 * Mirrors the live `/api/credits` payload: `methodologies` is a list, and the
 * order is deliberate -- Keener (the validated default) first, Elo (the second
 * opinion) after. The page renders in the order received and must not sort.
 */
const keener = {
  name: "Keener's method",
  citation:
    'J. P. Keener, "The Perron-Frobenius Theorem and the Ranking of Football Teams," SIAM Review, 35(1), 1993.',
  url: 'https://dl.acm.org/doi/10.1137/1035004',
  summary:
    "A team's rating depends recursively on the strength of the teams it beat, the same eigenvector idea behind PageRank applied to a win graph.",
} as const satisfies CreditsMethodologyOut

const elo = {
  name: 'Elo',
  citation:
    'Arpad E. Elo, The Rating of Chessplayers, Past and Present, Arco, 1978 -- as adapted for professional football by FiveThirtyEight (fivethirtyeight/nfl-elo-game).',
  url: 'https://github.com/fivethirtyeight/nfl-elo-game',
  summary:
    'Every team starts even and they trade points after each game: beat someone better than you and you take more from them than you would from a team you were supposed to beat.',
} as const satisfies CreditsMethodologyOut

const credits: CreditsOut = {
  methodologies: [keener, elo],
  data_sources: [
    {
      name: 'CollegeFootballData.com (CFBD)',
      url: 'https://collegefootballdata.com/test-mock',
      note: 'All game results are ingested from the CFBD API. This project performs no independent data collection and claims no ownership of the underlying game data.',
    },
    {
      name: 'nflverse (Lee Sharpe)',
      url: 'https://github.com/nflverse/nflverse-data/test-mock',
      note: 'NFL game results are ingested from nflverse, built on play-by-play data originated by Lee Sharpe.',
    },
  ],
}

describe('AboutPage', () => {
  beforeEach(() => {
    mockedFetchCredits.mockReset()
  })

  it('renders the "How This Works" headline', () => {
    mockedFetchCredits.mockReturnValue(new Promise(() => {}))

    render(<AboutPage />)

    expect(
      screen.getByRole('heading', { name: /how this works/i }),
    ).toBeInTheDocument()
  })

  it('shows a loading state while the credits request is in flight', () => {
    mockedFetchCredits.mockReturnValue(new Promise(() => {}))

    render(<AboutPage />)

    expect(screen.getByRole('status')).toBeInTheDocument()
  })

  it('renders every methodology name, summary, and citation link from the fetched credits, not hardcoded', async () => {
    mockedFetchCredits.mockResolvedValue(credits)

    render(<AboutPage />)

    // Awaited once so the fetch has resolved before the synchronous loop.
    await screen.findByRole('heading', { name: keener.name })

    for (const methodology of credits.methodologies) {
      const heading = screen.getByRole('heading', { name: methodology.name })
      const article = heading.closest('article')
      expect(article).not.toBeNull()
      const scope = within(article as HTMLElement)

      expect(scope.getByText(methodology.summary)).toBeInTheDocument()

      const link = scope.getByRole('link', { name: methodology.citation })
      expect(link).toHaveAttribute('href', methodology.url)
    }
  })

  it('credits Arpad Elo by name on the Elo methodology (PRD §5.6)', async () => {
    mockedFetchCredits.mockResolvedValue(credits)

    render(<AboutPage />)

    const heading = await screen.findByRole('heading', { name: 'Elo' })
    const scope = within(heading.closest('article') as HTMLElement)

    expect(scope.getByRole('link', { name: /arpad e\. elo/i })).toHaveAttribute(
      'href',
      'https://github.com/fivethirtyeight/nfl-elo-game',
    )
  })

  it('renders the methodologies in the order received, without sorting', async () => {
    mockedFetchCredits.mockResolvedValue(credits)

    render(<AboutPage />)

    await screen.findByRole('heading', { name: 'Elo' })

    const rendered = screen
      .getAllByRole('heading', { level: 3 })
      .map((heading) => heading.textContent)
    expect(rendered).toEqual([keener.name, elo.name])
  })

  it('renders no Keener-specific prose outside the fetched credits', async () => {
    mockedFetchCredits.mockResolvedValue({
      ...credits,
      methodologies: [
        {
          name: 'Only method',
          citation: 'Some citation.',
          url: 'https://example.com/only',
          summary: 'The only summary.',
        },
      ],
    })

    render(<AboutPage />)

    await screen.findByRole('heading', { name: 'Only method' })

    expect(screen.queryByText(/keener/i)).not.toBeInTheDocument()
  })

  it('renders every data source name, link, and note from the fetched credits, not hardcoded', async () => {
    mockedFetchCredits.mockResolvedValue(credits)

    render(<AboutPage />)

    for (const source of credits.data_sources) {
      const link = await screen.findByRole('link', {
        name: source.name,
      })
      expect(link).toHaveAttribute('href', source.url)
      expect(
        screen.getByText(source.note, { exact: false }),
      ).toBeInTheDocument()
    }
  })

  it('shows an error state when the credits request fails', async () => {
    mockedFetchCredits.mockRejectedValue(
      new VerdictNetworkError('Could not reach the API.'),
    )

    render(<AboutPage />)

    expect(await screen.findByRole('alert')).toHaveTextContent(
      /could not reach the api/i,
    )
  })
})
