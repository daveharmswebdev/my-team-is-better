import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, useLocation, useNavigate } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { AppRoutes } from './App'

/**
 * Each page is replaced by a stub that prints where it landed, so these tests
 * pin App's route table -- not what a page does with the query, which
 * fromShareSearch and parsePick own (and their tests pin).
 */
vi.mock('./pages/HomePage/HomePage', async () => {
  const { StubPage } = await import('./test/stubPage')
  return { HomePage: () => <StubPage name="home" /> }
})
vi.mock('./pages/AboutPage/AboutPage', async () => {
  const { StubPage } = await import('./test/stubPage')
  return { AboutPage: () => <StubPage name="about" /> }
})
vi.mock('./pages/PlayerLeadersPage/PlayerLeadersPage', async () => {
  const { StubPage } = await import('./test/stubPage')
  return { PlayerLeadersPage: () => <StubPage name="leaders" /> }
})
vi.mock('./pages/PlayerCareerPage/PlayerCareerPage', async () => {
  const { StubPage } = await import('./test/stubPage')
  return { PlayerCareerPage: () => <StubPage name="career" /> }
})
vi.mock('./pages/PlayerComparePage/PlayerComparePage', async () => {
  const { StubPage } = await import('./test/stubPage')
  return { PlayerComparePage: () => <StubPage name="compare" /> }
})

function BackButton() {
  const navigate = useNavigate()
  return (
    <button type="button" onClick={() => void navigate(-1)}>
      Back
    </button>
  )
}

function LocationProbe() {
  const location = useLocation()
  return (
    <p data-testid="location">
      {location.pathname}
      {location.search}
    </p>
  )
}

/** Renders the app's routes with `entries` as history, on the last one. */
function renderAt(...entries: string[]) {
  render(
    <MemoryRouter initialEntries={entries} initialIndex={entries.length - 1}>
      <AppRoutes />
      <LocationProbe />
      <BackButton />
    </MemoryRouter>,
  )
}

const VERDICT_SEARCH =
  '?q=team_case&sport=cfb&year=2005&engine=keener&team=Texas&for=Texas+A%26M'

describe('App routes: minted share links (issue #185)', () => {
  it('lands /s?<query> on the home page with the same query', async () => {
    renderAt(`/s${VERDICT_SEARCH}`)

    expect(await screen.findByTestId('landed')).toHaveTextContent('home')
    expect(screen.getByTestId('location')).toHaveTextContent(
      `/${VERDICT_SEARCH}`,
    )
  })

  it('lands /s/nfl/compare?a=&b= on the compare page with the same query', async () => {
    renderAt('/s/nfl/compare?a=2153701690&b=2072050236')

    expect(await screen.findByTestId('landed')).toHaveTextContent('compare')
    expect(screen.getByTestId('location')).toHaveTextContent(
      '/nfl/compare?a=2153701690&b=2072050236',
    )
  })

  it('passes a malformed query through untouched for the page to judge', async () => {
    renderAt('/s/nfl/compare?a=nope&b=')

    expect(await screen.findByTestId('landed')).toHaveTextContent('compare')
    expect(screen.getByTestId('location')).toHaveTextContent(
      '/nfl/compare?a=nope&b=',
    )
  })

  it('replaces the /s entry, so Back skips it', async () => {
    const user = userEvent.setup()
    renderAt('/about', `/s${VERDICT_SEARCH}`)
    expect(await screen.findByTestId('landed')).toHaveTextContent('home')

    await user.click(screen.getByRole('button', { name: 'Back' }))

    expect(await screen.findByTestId('landed')).toHaveTextContent('about')
    expect(screen.getByTestId('location')).toHaveTextContent('/about')
  })

  it('keeps the old links working as they are', async () => {
    renderAt(`/${VERDICT_SEARCH}`)
    expect(await screen.findByTestId('landed')).toHaveTextContent('home')
    expect(screen.getByTestId('location')).toHaveTextContent(
      `/${VERDICT_SEARCH}`,
    )
  })
})
