import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useEffect } from 'react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AppShell } from './AppShell'

function renderWithRoute(initialEntry: string) {
  render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Routes>
        <Route element={<AppShell />}>
          <Route path="/" element={<p>Home content</p>} />
          <Route path="/about" element={<p>About content</p>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  )
}

describe('AppShell', () => {
  it('renders the matched child route via the outlet', () => {
    renderWithRoute('/')

    expect(screen.getByText('Home content')).toBeInTheDocument()
  })

  it('links to /about from the nav', () => {
    renderWithRoute('/')

    expect(
      screen.getByRole('link', { name: /how this works/i }),
    ).toHaveAttribute('href', '/about')
  })

  it('links to the NFL leaders from the nav (issue #296)', () => {
    renderWithRoute('/')

    const nav = screen.getByRole('navigation', { name: 'Primary' })
    expect(
      within(nav).getByRole('link', { name: 'NFL Leaders' }),
    ).toHaveAttribute('href', '/nfl/leaders')
  })

  it('links to the player compare page from the nav (issue #301)', () => {
    renderWithRoute('/')

    const nav = screen.getByRole('navigation', { name: 'Primary' })
    expect(
      within(nav).getByRole('link', { name: 'Compare Players' }),
    ).toHaveAttribute('href', '/nfl/compare')
  })

  it('links home from the site name', () => {
    renderWithRoute('/about')

    expect(screen.getByText('About content')).toBeInTheDocument()
    expect(
      screen.getByRole('link', { name: /^my team is better$/i }),
    ).toHaveAttribute('href', '/')
  })

  it('also links to /about from the footer', () => {
    renderWithRoute('/')

    const footer = screen.getByRole('contentinfo')
    expect(
      screen.getByRole('link', {
        name: /credits/i,
      }),
    ).toHaveAttribute('href', '/about')
    expect(footer).toBeInTheDocument()
  })
})

function ThrowsInRender(): never {
  throw new Error('page blew up while rendering')
}

function ThrowsInEffect() {
  useEffect(() => {
    throw new Error('page blew up in an effect')
  }, [])
  return <p>Effect page content</p>
}

function renderWithBrokenRoutes(initialEntry: string) {
  render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Routes>
        <Route element={<AppShell />}>
          <Route path="/" element={<p>Home content</p>} />
          <Route path="/about" element={<p>About content</p>} />
          <Route path="/nfl/leaders" element={<ThrowsInRender />} />
          <Route path="/nfl/compare" element={<ThrowsInEffect />} />
        </Route>
      </Routes>
    </MemoryRouter>,
  )
}

/**
 * Issue #268: one uncaught render or effect error in a page must not blank
 * the whole app. The shell's route-level boundary shows the narrator's
 * fallback, keeps the nav usable, and resets when the visitor navigates.
 */
describe('AppShell route error boundary (issue #268)', () => {
  beforeEach(() => {
    // React reports every caught error through console.error; keep the
    // output readable without hiding real failures (assertions still run).
    vi.spyOn(console, 'error').mockImplementation(() => {})
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('shows the fallback and keeps the nav when a page throws during render', () => {
    renderWithBrokenRoutes('/nfl/leaders')

    const alert = screen.getByRole('alert')
    expect(alert).toHaveTextContent(/that's on us, not you/i)
    expect(alert).not.toHaveTextContent('page blew up')
    expect(
      within(alert).getByRole('link', { name: /back to the start/i }),
    ).toHaveAttribute('href', '/')
    const nav = screen.getByRole('navigation', { name: 'Primary' })
    expect(
      within(nav).getByRole('link', { name: 'How This Works' }),
    ).toBeInTheDocument()
  })

  it('shows the fallback and keeps the nav when a page throws in an effect', () => {
    renderWithBrokenRoutes('/nfl/compare')

    expect(screen.getByRole('alert')).toHaveTextContent(
      /that's on us, not you/i,
    )
    expect(screen.queryByText('Effect page content')).not.toBeInTheDocument()
    expect(
      screen.getByRole('navigation', { name: 'Primary' }),
    ).toBeInTheDocument()
  })

  it('resets when the visitor navigates to another route', async () => {
    const user = userEvent.setup()
    renderWithBrokenRoutes('/nfl/leaders')
    expect(screen.getByRole('alert')).toBeInTheDocument()

    const nav = screen.getByRole('navigation', { name: 'Primary' })
    await user.click(within(nav).getByRole('link', { name: 'How This Works' }))

    expect(screen.getByText('About content')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('resets via the fallback link back to the start', async () => {
    const user = userEvent.setup()
    renderWithBrokenRoutes('/nfl/compare')

    await user.click(screen.getByRole('link', { name: /back to the start/i }))

    expect(screen.getByText('Home content')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })
})
