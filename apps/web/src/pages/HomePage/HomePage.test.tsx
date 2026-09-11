import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { VerdictApiError, VerdictNetworkError } from '../../lib/api/client'
import { HomePage } from './HomePage'

vi.mock('../../lib/api/client', async () => {
  const actual = await vi.importActual<typeof import('../../lib/api/client')>(
    '../../lib/api/client',
  )
  return {
    ...actual,
    fetchChampion: vi.fn(),
    fetchTeamCase: vi.fn(),
    fetchCompare: vi.fn(),
  }
})

import {
  fetchChampion,
  fetchCompare,
  fetchTeamCase,
} from '../../lib/api/client'

const mockedFetchChampion = vi.mocked(fetchChampion)
const mockedFetchTeamCase = vi.mocked(fetchTeamCase)
const mockedFetchCompare = vi.mocked(fetchCompare)

describe('HomePage', () => {
  beforeEach(() => {
    window.localStorage.clear()
    mockedFetchChampion.mockReset()
    mockedFetchTeamCase.mockReset()
    mockedFetchCompare.mockReset()
  })

  it('submits a champion question and renders the resulting verdict', async () => {
    const user = userEvent.setup()
    mockedFetchChampion.mockResolvedValue({
      evidence: {
        year: 2005,
        method: 'keener',
        team_id: 1,
        team_name: 'Texas',
        rank: 1,
        rating: 12.3,
        wins: 13,
        losses: 0,
        rating_breakdown: { entries: [], residual_contribution: 12.3 },
        games: [],
        quality_wins: [],
        worst_loss: null,
      },
      narration: { text: 'Texas, full stop.', contested: false, cached: false },
    })

    render(<HomePage />)
    await user.clear(screen.getByLabelText(/year/i))
    await user.type(screen.getByLabelText(/year/i), '2005')
    await user.click(screen.getByRole('button', { name: /get the verdict/i }))

    expect(await screen.findByText('Texas, full stop.')).toBeInTheDocument()
    expect(mockedFetchChampion).toHaveBeenCalledWith({
      year: 2005,
      user_team: null,
    })
  })

  it('re-submits with the exact candidate name after an ambiguous_team error', async () => {
    const user = userEvent.setup()
    mockedFetchTeamCase
      .mockRejectedValueOnce(
        new VerdictApiError(422, {
          error: 'ambiguous_team',
          query: 'Texas St',
          candidates: ['Texas State'],
        }),
      )
      .mockResolvedValueOnce({
        evidence: {
          year: 2005,
          method: 'keener',
          team_id: 3,
          team_name: 'Texas State',
          rank: 80,
          rating: 1.1,
          wins: 5,
          losses: 6,
          rating_breakdown: { entries: [], residual_contribution: 1.1 },
          games: [],
          quality_wins: [],
          worst_loss: null,
        },
        narration: {
          text: 'Texas State had a mediocre year.',
          contested: false,
          cached: false,
        },
      })

    render(<HomePage />)
    await user.selectOptions(
      screen.getByLabelText(/what do you want to know/i),
      'team_case',
    )
    await user.clear(screen.getByLabelText(/year/i))
    await user.type(screen.getByLabelText(/year/i), '2005')
    await user.type(screen.getByLabelText(/^team$/i), 'Texas St')
    await user.click(screen.getByRole('button', { name: /get the verdict/i }))

    const candidateButton = await screen.findByRole('button', {
      name: 'Texas State',
    })
    await user.click(candidateButton)

    expect(
      await screen.findByText('Texas State had a mediocre year.'),
    ).toBeInTheDocument()
    expect(mockedFetchTeamCase).toHaveBeenLastCalledWith({
      year: 2005,
      team: 'Texas State',
      user_team: null,
    })
  })

  it('renders a generic failure state on a network error', async () => {
    const user = userEvent.setup()
    mockedFetchChampion.mockRejectedValue(
      new VerdictNetworkError('Could not reach the API.'),
    )

    render(<HomePage />)
    await user.clear(screen.getByLabelText(/year/i))
    await user.type(screen.getByLabelText(/year/i), '2005')
    await user.click(screen.getByRole('button', { name: /get the verdict/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent(
      /could not reach the api/i,
    )
  })
})
