import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { VerdictNetworkError } from '../../lib/api/client'
import type { CreditsOut } from '../../lib/api/types'
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

const credits: CreditsOut = {
  methodology: {
    name: 'Keener',
    citation:
      'Keener, J. P. (1993). The Perron-Frobenius theorem and the ranking of football teams. The American Mathematical Monthly, 100(1), 80-93.',
    url: 'https://www.jstor.org/stable/2324033',
    summary: 'Eigenvector-based strength-of-schedule ranking.',
  },
  data_source: {
    name: 'CollegeFootballData.com (CFBD)',
    url: 'https://collegefootballdata.com/test-mock',
    note: 'All game results are ingested from the CFBD API. This project performs no independent data collection and claims no ownership of the underlying game data.',
  },
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

  it('renders the citation text and link from the fetched credits, not hardcoded', async () => {
    mockedFetchCredits.mockResolvedValue(credits)

    render(<AboutPage />)

    const link = await screen.findByRole('link', {
      name: /keener, j\. p\./i,
    })
    expect(link).toHaveTextContent(credits.methodology.citation)
    expect(link).toHaveAttribute('href', credits.methodology.url)
  })

  it('renders the data source name, link, and note from the fetched credits, not hardcoded', async () => {
    mockedFetchCredits.mockResolvedValue(credits)

    render(<AboutPage />)

    const link = await screen.findByRole('link', {
      name: credits.data_source.name,
    })
    expect(link).toHaveAttribute('href', credits.data_source.url)
    expect(
      screen.getByText(credits.data_source.note, { exact: false }),
    ).toBeInTheDocument()
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
