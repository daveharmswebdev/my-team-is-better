import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { NETWORK_ERROR_COPY, SERVER_ERROR_COPY } from '../../lib/api/client'
import { VerdictError } from './VerdictError'

describe('VerdictError', () => {
  it('renders the unknown_year message plus clickable available years', async () => {
    const onSelectYear = vi.fn()
    const user = userEvent.setup()
    render(
      <VerdictError
        state={{
          kind: 'unknown_year',
          body: {
            error: 'unknown_year',
            year: 1899,
            available_years: [2004, 2005],
          },
        }}
        onSelectYear={onSelectYear}
      />,
    )

    expect(screen.getByText(/1899/)).toBeInTheDocument()
    const yearButton = screen.getByRole('button', { name: '2005' })
    await user.click(yearButton)
    expect(onSelectYear).toHaveBeenCalledWith(2005)
  })

  it('renders the ambiguous_team message plus clickable candidates', async () => {
    const onSelectCandidate = vi.fn()
    const user = userEvent.setup()
    render(
      <VerdictError
        state={{
          kind: 'ambiguous_team',
          body: {
            error: 'ambiguous_team',
            query: 'Texas St',
            candidates: ['Texas', 'Texas State'],
          },
        }}
        onSelectCandidate={onSelectCandidate}
      />,
    )

    expect(screen.getByText(/did you mean/i)).toBeInTheDocument()
    const candidateButton = screen.getByRole('button', { name: 'Texas State' })
    await user.click(candidateButton)
    expect(onSelectCandidate).toHaveBeenCalledWith('Texas State')
  })

  describe('unknown_team (issue #100)', () => {
    it('renders a single not-found state naming the season and league, with nothing to pick', () => {
      render(
        <VerdictError
          state={{
            kind: 'unknown_team',
            body: {
              error: 'unknown_team',
              query: 'Abilene Christian',
              year: 2010,
              sport: 'cfb',
            },
          }}
          onSelectCandidate={vi.fn()}
        />,
      )

      const alert = screen.getByRole('alert')
      expect(alert).toHaveTextContent(/Abilene Christian/)
      expect(alert).toHaveTextContent(/2010 college football/i)
      // The exact defect being fixed: never claims the name was ambiguous,
      // and never renders a pick list -- empty or otherwise. Correction
      // pills were removed from this kind outright, so a `list` node here
      // means a regression, not an empty array.
      expect(alert).not.toHaveTextContent(/did you mean/i)
      expect(alert).not.toHaveTextContent(/more than one team/i)
      expect(screen.queryByRole('list')).not.toBeInTheDocument()
      expect(screen.queryAllByRole('listitem')).toHaveLength(0)
      expect(screen.queryByRole('button')).not.toBeInTheDocument()
      // ...and it says what to do instead.
      expect(alert).toHaveTextContent(/season/i)
      expect(alert).toHaveTextContent(/league/i)
    })

    it('names the league as the NFL for an nfl question', () => {
      render(
        <VerdictError
          state={{
            kind: 'unknown_team',
            body: {
              error: 'unknown_team',
              query: 'Baltimore Colts',
              year: 2018,
              sport: 'nfl',
            },
          }}
        />,
      )

      expect(screen.getByRole('alert')).toHaveTextContent(/2018 NFL/)
      expect(screen.queryByRole('list')).not.toBeInTheDocument()
    })
  })

  it('renders the same_team_comparison message', () => {
    render(
      <VerdictError
        state={{
          kind: 'same_team_comparison',
          body: { error: 'same_team_comparison', team_name: 'Texas' },
        }}
      />,
    )

    expect(screen.getByText(/Texas/)).toBeInTheDocument()
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })

  it('renders the network error message', () => {
    render(
      <VerdictError
        state={{ kind: 'network_error', message: NETWORK_ERROR_COPY }}
      />,
    )

    expect(screen.getByText(NETWORK_ERROR_COPY)).toBeInTheDocument()
  })

  it('renders an unmapped HTTP error in the same plain system-error display (issue #215)', () => {
    render(
      <VerdictError
        state={{ kind: 'network_error', message: SERVER_ERROR_COPY }}
      />,
    )

    const alert = screen.getByRole('alert')
    expect(alert).toHaveTextContent(SERVER_ERROR_COPY)
    expect(alert).not.toHaveTextContent(/status/i)
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })
})
