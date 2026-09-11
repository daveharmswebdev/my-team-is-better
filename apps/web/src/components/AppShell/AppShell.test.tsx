import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
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
