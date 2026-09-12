import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { VerdictApiError, VerdictNetworkError } from '../../lib/api/client'
import type { TeamCaseEnvelope, TeamsOut } from '../../lib/api/types'
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
    fetchYears: vi.fn(),
    fetchTeams: vi.fn(),
  }
})

import {
  fetchChampion,
  fetchCompare,
  fetchTeamCase,
  fetchTeams,
  fetchYears,
} from '../../lib/api/client'

const mockedFetchChampion = vi.mocked(fetchChampion)
const mockedFetchTeamCase = vi.mocked(fetchTeamCase)
const mockedFetchCompare = vi.mocked(fetchCompare)
const mockedFetchYears = vi.mocked(fetchYears)
const mockedFetchTeams = vi.mocked(fetchTeams)

const TEAMS: TeamsOut = {
  teams: ['Texas', 'Texas State', 'USC'],
  team_details: [
    { name: 'Texas', mascot: 'Longhorns', aliases: ['TEX'] },
    { name: 'Texas State', mascot: 'Bobcats', aliases: [] },
    { name: 'USC', mascot: 'Trojans', aliases: [] },
  ],
}

/** A minimal successful team-case/champion envelope, parameterised by the
 * two fields these tests actually assert on. */
function envelopeFor(teamName: string, narration: string): TeamCaseEnvelope {
  return {
    evidence: {
      year: 2005,
      method: 'keener',
      team_id: 1,
      team_name: teamName,
      rank: 1,
      rating: 12.3,
      wins: 13,
      losses: 0,
      rating_breakdown: { entries: [], residual_contribution: 12.3 },
      games: [],
      quality_wins: [],
      worst_loss: null,
    },
    narration: { text: narration, contested: false, cached: false },
  }
}

const UNKNOWN_YEAR_ERROR = new VerdictApiError(404, {
  error: 'unknown_year',
  year: new Date().getFullYear(),
  available_years: [2004, 2005, 2018],
})

describe('HomePage', () => {
  beforeEach(() => {
    window.localStorage.clear()
    mockedFetchChampion.mockReset()
    mockedFetchTeamCase.mockReset()
    mockedFetchCompare.mockReset()
    mockedFetchYears.mockReset()
    mockedFetchTeams.mockReset()
    mockedFetchYears.mockResolvedValue({ years: [2004, 2005, 2018] })
    mockedFetchTeams.mockResolvedValue(TEAMS)
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
      sport: 'cfb',
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
      sport: 'cfb',
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

  describe('pill corrections update the visible form (issue #38)', () => {
    it('updates the Year input, not just the verdict, when a year pill is picked', async () => {
      const user = userEvent.setup()
      mockedFetchChampion
        .mockRejectedValueOnce(UNKNOWN_YEAR_ERROR)
        .mockResolvedValueOnce(envelopeFor('Texas', 'Texas, full stop.'))

      render(<HomePage />)
      await user.click(screen.getByRole('button', { name: /get the verdict/i }))

      await user.click(await screen.findByRole('button', { name: '2018' }))

      expect(await screen.findByText('Texas, full stop.')).toBeInTheDocument()
      expect(mockedFetchChampion).toHaveBeenLastCalledWith({
        year: 2018,
        user_team: null,
        sport: 'cfb',
      })
      // The point of the issue: the form must agree with what was asked.
      expect(screen.getByLabelText(/year/i)).toHaveValue(2018)
    })

    it('updates the team input when an ambiguous-team candidate is picked', async () => {
      const user = userEvent.setup()
      mockedFetchTeamCase
        .mockRejectedValueOnce(
          new VerdictApiError(422, {
            error: 'ambiguous_team',
            query: 'Texas St',
            candidates: ['Texas State'],
          }),
        )
        .mockResolvedValueOnce(
          envelopeFor('Texas State', 'Texas State had a mediocre year.'),
        )

      render(<HomePage />)
      await user.selectOptions(
        screen.getByLabelText(/what do you want to know/i),
        'team_case',
      )
      await user.clear(screen.getByLabelText(/year/i))
      await user.type(screen.getByLabelText(/year/i), '2005')
      await user.type(screen.getByLabelText(/^team$/i), 'Texas St')
      await user.click(screen.getByRole('button', { name: /get the verdict/i }))

      await user.click(
        await screen.findByRole('button', { name: 'Texas State' }),
      )

      expect(
        await screen.findByText('Texas State had a mediocre year.'),
      ).toBeInTheDocument()
      expect(screen.getByLabelText(/^team$/i)).toHaveValue('Texas State')
      // The rest of the form survives the correction.
      expect(screen.getByLabelText(/year/i)).toHaveValue(2005)
      expect(screen.getByLabelText(/what do you want to know/i)).toHaveValue(
        'team_case',
      )
    })

    it('updates only the ambiguous side of a compare question', async () => {
      const user = userEvent.setup()
      mockedFetchCompare.mockRejectedValueOnce(
        new VerdictApiError(422, {
          error: 'ambiguous_team',
          query: 'Texas St',
          candidates: ['Texas State'],
        }),
      )
      mockedFetchCompare.mockRejectedValueOnce(
        new VerdictNetworkError('Could not reach the API.'),
      )

      render(<HomePage />)
      await user.selectOptions(
        screen.getByLabelText(/what do you want to know/i),
        'compare',
      )
      await user.clear(screen.getByLabelText(/year/i))
      await user.type(screen.getByLabelText(/year/i), '2005')
      await user.type(screen.getByLabelText(/team a/i), 'USC')
      await user.type(screen.getByLabelText(/team b/i), 'Texas St')
      await user.click(screen.getByRole('button', { name: /get the verdict/i }))

      await user.click(
        await screen.findByRole('button', { name: 'Texas State' }),
      )

      await waitFor(() =>
        expect(mockedFetchCompare).toHaveBeenLastCalledWith({
          year: 2005,
          team_a: 'USC',
          team_b: 'Texas State',
          user_team: null,
          sport: 'cfb',
        }),
      )
      expect(screen.getByLabelText(/team a/i)).toHaveValue('USC')
      expect(screen.getByLabelText(/team b/i)).toHaveValue('Texas State')
    })

    it('keeps an unsubmitted user team, the league, and the corrected year across the correction', async () => {
      const user = userEvent.setup()
      mockedFetchChampion
        .mockRejectedValueOnce(UNKNOWN_YEAR_ERROR)
        .mockResolvedValueOnce(envelopeFor('Texas', 'Texas, full stop.'))

      render(<HomePage />)
      await user.click(screen.getByRole('radio', { name: /nfl/i }))
      await user.click(screen.getByRole('button', { name: /get the verdict/i }))

      // Typed after the failed submission, so it was never part of it.
      await user.type(screen.getByLabelText(/your team/i), 'Bengals')

      // A catalog request that is already in flight when the correction is
      // applied must not land on the remounted form and undo it.
      let releaseStaleFetch: (value: TeamsOut) => void = () => {}
      mockedFetchTeams.mockReturnValueOnce(
        new Promise<TeamsOut>((resolvePromise) => {
          releaseStaleFetch = resolvePromise
        }),
      )

      await user.click(await screen.findByRole('button', { name: '2018' }))
      releaseStaleFetch({ teams: [], team_details: [] })

      expect(await screen.findByText('Texas, full stop.')).toBeInTheDocument()
      expect(screen.getByLabelText(/year/i)).toHaveValue(2018)
      expect(screen.getByRole('radio', { name: /nfl/i })).toBeChecked()
      expect(screen.getByLabelText(/your team/i)).toHaveValue('Bengals')
      // The pill re-asks *the question that was asked*, with one field
      // corrected -- not a different question assembled from edits made
      // after the submit button was pressed. So the re-ask carries the
      // submitted `user_team` (none), while the field keeps what the user
      // has since typed for their next submission.
      expect(mockedFetchChampion).toHaveBeenLastCalledWith({
        year: 2018,
        user_team: null,
        sport: 'nfl',
      })
    })
  })
})
