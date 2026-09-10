import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
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
        state={{ kind: 'network_error', message: 'Could not reach the API.' }}
      />,
    )

    expect(screen.getByText('Could not reach the API.')).toBeInTheDocument()
  })
})
