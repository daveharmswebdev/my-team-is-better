import { act, render, screen, waitFor, within } from '@testing-library/react'
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
      ties: 0,
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
  // Fixed, not the calendar year: nothing in these tests may depend on today.
  year: 2019,
  available_years: [2004, 2005, 2018],
})

/**
 * `QuestionForm` defaults Year to the newest season `/api/years` reports
 * (issue #136) -- 2018 under this file's catalog -- once that request lands.
 * Tests that clear and retype the Year wait for it first: otherwise the
 * default can arrive between the clear and the typing, and the typed digits
 * append to it.
 */
async function waitForDefaultYear() {
  await waitFor(() => expect(screen.getByLabelText(/year/i)).toHaveValue(2018))
}

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
        ties: 0,
        rating_breakdown: { entries: [], residual_contribution: 12.3 },
        games: [],
        quality_wins: [],
        worst_loss: null,
      },
      narration: { text: 'Texas, full stop.', contested: false, cached: false },
    })

    render(<HomePage />)
    await waitForDefaultYear()
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
          ties: 0,
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
    await waitForDefaultYear()
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
    await waitForDefaultYear()
    await user.clear(screen.getByLabelText(/year/i))
    await user.type(screen.getByLabelText(/year/i), '2005')
    await user.click(screen.getByRole('button', { name: /get the verdict/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent(
      /could not reach the api/i,
    )
  })

  it('renders an unknown_team error as a not-found state with no correction pills', async () => {
    const user = userEvent.setup()
    mockedFetchTeamCase.mockRejectedValue(
      new VerdictApiError(404, {
        error: 'unknown_team',
        query: 'Abilene Christian',
        year: 2005,
        sport: 'cfb',
      }),
    )

    render(<HomePage />)
    await user.selectOptions(
      screen.getByLabelText(/what do you want to know/i),
      'team_case',
    )
    await waitForDefaultYear()
    await user.clear(screen.getByLabelText(/year/i))
    await user.type(screen.getByLabelText(/year/i), '2005')
    await user.type(screen.getByLabelText(/^team$/i), 'Abilene Christian')
    await user.click(screen.getByRole('button', { name: /get the verdict/i }))

    // Scoped to the alert: the page itself always has buttons (submit, and
    // possibly a stale-value clear), so an unscoped button query would say
    // nothing about whether pills came back.
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent(/Abilene Christian/)
    expect(alert).toHaveTextContent(/2005 college football/i)
    expect(within(alert).queryByRole('list')).not.toBeInTheDocument()
    expect(within(alert).queryByRole('listitem')).not.toBeInTheDocument()
    expect(within(alert).queryByRole('button')).not.toBeInTheDocument()
  })

  describe('pill corrections update the visible form (issue #38)', () => {
    it('updates the Year input, not just the verdict, when a year pill is picked', async () => {
      const user = userEvent.setup()
      mockedFetchChampion
        .mockRejectedValueOnce(UNKNOWN_YEAR_ERROR)
        .mockResolvedValueOnce(envelopeFor('Texas', 'Texas, full stop.'))

      render(<HomePage />)
      // The Year field defaults to the newest catalog season (issue #136),
      // so the submit button only enables once `/api/years` has landed.
      const submit = screen.getByRole('button', { name: /get the verdict/i })
      await waitFor(() => expect(submit).not.toBeDisabled())
      await user.click(submit)

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
      await waitForDefaultYear()
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
      await waitForDefaultYear()
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
      // Wait for the NFL catalog's newest season to fill the Year field
      // (issue #136) -- until then the submit button is disabled.
      const submit = screen.getByRole('button', { name: /get the verdict/i })
      await waitFor(() => expect(submit).not.toBeDisabled())
      await user.click(submit)

      // Typed after the failed submission, so it was never part of it.
      await user.type(screen.getByLabelText(/your team/i), 'Bengals')

      await user.click(await screen.findByRole('button', { name: '2018' }))

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

    /**
     * Issue #101: a team-catalog request genuinely in flight at the moment a
     * correction pill is clicked. The test this replaced resolved a pending
     * promise "across" the correction with *no* request outstanding at the
     * click, and its promise was then consumed by the remounted form's own
     * first fetch -- it could not fail for the reason it named.
     *
     * What this does prove: the request is outstanding at the click (asserted,
     * not assumed), and its late response does not reach the corrected form --
     * no "No teams found for 2005" hint, no reverted year.
     *
     * What it does NOT prove: that `QuestionForm`'s `cancelled` guard carries
     * that weight. The pill remounts the form (`HomePage` changes its `key`),
     * so the old form's effect cleanup runs and React discards the stale
     * `setState` on the unmounted instance whether or not the guard is there.
     * The guard is load-bearing only on a form that stays mounted, which the
     * out-of-order tests in `QuestionForm.test.tsx` cover.
     */
    it('does not let a team-list request in flight at the correction reach the corrected form', async () => {
      const user = userEvent.setup()
      mockedFetchChampion
        .mockRejectedValueOnce(UNKNOWN_YEAR_ERROR)
        .mockResolvedValueOnce(envelopeFor('Texas', 'Texas, full stop.'))
      let release2005Teams: () => void = () => {}
      let teams2005Settled = false
      mockedFetchTeams.mockImplementation((_sport, year) =>
        year === 2005
          ? new Promise<TeamsOut>((resolvePromise) => {
              release2005Teams = () => {
                teams2005Settled = true
                // Empty, so a response that leaked onto the corrected form
                // would show up as the year-scoped empty hint.
                resolvePromise({ teams: [], team_details: [] })
              }
            })
          : Promise.resolve(TEAMS),
      )

      render(<HomePage />)
      const submit = screen.getByRole('button', { name: /get the verdict/i })
      await waitFor(() => expect(submit).not.toBeDisabled())
      await user.click(submit)
      const pill = await screen.findByRole('button', { name: '2018' })

      // An edit made after the failed submission, allowed to settle past the
      // form's debounce so its team-list request actually goes out.
      await user.clear(screen.getByLabelText(/year/i))
      await user.type(screen.getByLabelText(/year/i), '2005')
      await waitFor(
        () => expect(mockedFetchTeams).toHaveBeenLastCalledWith('cfb', 2005),
        { timeout: 2000 },
      )
      const callsBeforeCorrection = mockedFetchTeams.mock.calls.length

      // The precondition the old test only claimed: in flight at the click.
      expect(teams2005Settled).toBe(false)
      await user.click(pill)

      expect(await screen.findByText('Texas, full stop.')).toBeInTheDocument()
      // The corrected form issued its own request rather than inheriting the
      // outstanding one.
      await waitFor(() =>
        expect(
          mockedFetchTeams.mock.calls.slice(callsBeforeCorrection),
        ).toContainEqual(['cfb', 2018]),
      )

      release2005Teams()
      await act(async () => {
        await new Promise((resolveWait) => setTimeout(resolveWait, 0))
      })

      expect(teams2005Settled).toBe(true)
      expect(screen.getByLabelText(/year/i)).toHaveValue(2018)
      expect(screen.queryByText(/no teams found for/i)).not.toBeInTheDocument()
      expect(mockedFetchChampion).toHaveBeenLastCalledWith({
        year: 2018,
        user_team: null,
        sport: 'cfb',
      })
    })
  })
})
