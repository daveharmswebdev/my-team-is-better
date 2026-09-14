import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { StrictMode } from 'react'
import { MemoryRouter, useLocation, useNavigationType } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { YEAR_DEBOUNCE_MS } from '../../components/QuestionForm/QuestionForm'
import { VerdictApiError, VerdictNetworkError } from '../../lib/api/client'
import type {
  ComparisonEnvelope,
  ComparisonTeamSummaryOut,
  TeamCaseEnvelope,
  TeamsOut,
} from '../../lib/api/types'
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
      elo_ledger: null,
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

/**
 * The year pill the correction tests pick. Deliberately *not* 2018, the
 * newest season in this file's `/api/years` catalog: the corrected form is
 * remounted, and a remounted form with no `initialYear` defaults to that
 * newest season on its own, so a 2018 correction would look applied even if
 * `HomePage` never passed it down.
 */
const CORRECTED_YEAR = 2005

/** The Year edit whose team-list request is held open across a correction. */
const IN_FLIGHT_YEAR = 2004

/**
 * Whether `promise` has settled yet, read off the promise itself rather than
 * a flag the test flips when it releases one. An already-settled promise's
 * reaction beats a zero-delay timer; a pending one loses to it.
 */
async function hasSettled(promise: Promise<unknown>): Promise<boolean> {
  let settled = false
  await act(async () => {
    settled = await Promise.race([
      promise.then(
        () => true,
        () => true,
      ),
      new Promise<boolean>((resolveRace) =>
        setTimeout(() => resolveRace(false), 0),
      ),
    ])
  })
  return settled
}

/**
 * Asserts `assertion` holds continuously for two debounce intervals,
 * re-checking every 20ms, so a stale response deferred by a timer still
 * lands inside the window instead of after a one-shot absence check.
 */
async function expectThroughout(assertion: () => void) {
  const deadline = Date.now() + YEAR_DEBOUNCE_MS * 2
  do {
    assertion()
    await act(async () => {
      await new Promise((resolveWait) => setTimeout(resolveWait, 20))
    })
  } while (Date.now() < deadline)
  assertion()
}

/** A minimal successful compare envelope, answered by Elo. */
function comparisonEnvelopeFor(
  teamA: string,
  teamB: string,
  narration: string,
): ComparisonEnvelope {
  const summary = (
    teamId: number,
    teamName: string,
    rating: number,
  ): ComparisonTeamSummaryOut => ({
    team_id: teamId,
    team_name: teamName,
    rank: teamId,
    rating,
    wins: 12,
    losses: 1,
    ties: 0,
    rating_breakdown: { entries: [], residual_contribution: 0 },
    elo_ledger: null,
    quality_wins: [],
    worst_loss: null,
  })
  return {
    evidence: {
      year: 2005,
      method: 'elo',
      team_a: summary(1, teamA, 1933.19),
      team_b: summary(2, teamB, 1891.83),
      head_to_head: { played: false, meetings: [] },
      common_opponents: [],
      rating_diff: 41.36,
      verdict: `${teamA} was better.`,
    },
    narration: { text: narration, contested: false, cached: false },
  }
}

/** What the address bar says, and how it last changed (issue #184). */
function LocationProbe() {
  const location = useLocation()
  const navigationType = useNavigationType()
  return (
    <div hidden>
      <span data-testid="location-search">{location.search}</span>
      <span data-testid="navigation-type">{navigationType}</span>
    </div>
  )
}

/**
 * `HomePage` reads and writes the URL (issue #184), so every render needs a
 * router. `strict` wraps it in `StrictMode`, as `main.tsx` renders the app,
 * for the tests where a double effect run could re-fire a share-link landing.
 */
function renderHomePage(initialEntry = '/', { strict = false } = {}) {
  const tree = (
    <MemoryRouter initialEntries={[initialEntry]}>
      <HomePage />
      <LocationProbe />
    </MemoryRouter>
  )
  return render(strict ? <StrictMode>{tree}</StrictMode> : tree)
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

  /**
   * Issue #184: a verdict is shared as a link to its *question*. Landing on
   * one fills in the form and re-asks the API exactly once, with no click;
   * every run keeps the address bar on the link of the question just asked.
   */
  describe('share links (issue #184)', () => {
    const TEXAS_USC_LINK =
      '/?q=compare&sport=cfb&year=2005&engine=elo&a=Texas&b=USC&for=Texas'
    /** "Texas St" is ambiguous, so this landing answers with a pill. */
    const AMBIGUOUS_LINK =
      '/?q=compare&sport=cfb&year=2005&engine=elo&a=Texas+St&b=USC&for=Texas'
    const AMBIGUOUS_TEXAS_ST = new VerdictApiError(422, {
      error: 'ambiguous_team',
      query: 'Texas St',
      candidates: ['Texas State'],
    })

    afterEach(() => {
      Reflect.deleteProperty(window.navigator, 'clipboard')
    })

    it('answers a share link on landing, exactly once even under StrictMode, with no interaction', async () => {
      mockedFetchCompare.mockResolvedValue(
        comparisonEnvelopeFor('Texas', 'USC', 'Texas edges USC.'),
      )

      renderHomePage(TEXAS_USC_LINK, { strict: true })

      expect(await screen.findByText('Texas edges USC.')).toBeInTheDocument()
      expect(mockedFetchCompare).toHaveBeenCalledWith({
        year: 2005,
        team_a: 'Texas',
        team_b: 'USC',
        user_team: 'Texas',
        sport: 'cfb',
        method: 'elo',
      })
      await expectThroughout(() =>
        expect(mockedFetchCompare).toHaveBeenCalledTimes(1),
      )
      expect(mockedFetchChampion).not.toHaveBeenCalled()
      expect(mockedFetchTeamCase).not.toHaveBeenCalled()
      // The visible form agrees with the question the link asked.
      expect(screen.getByLabelText(/what do you want to know/i)).toHaveValue(
        'compare',
      )
      expect(screen.getByLabelText(/year/i)).toHaveValue(2005)
      expect(screen.getByLabelText(/team a/i)).toHaveValue('Texas')
      expect(screen.getByLabelText(/team b/i)).toHaveValue('USC')
      expect(
        screen.getByRole('radio', { name: 'Elo (second opinion)' }),
      ).toBeChecked()
    })

    it('shows the link\'s "for" team in "your team" without saving it as yours', async () => {
      mockedFetchCompare.mockResolvedValue(
        comparisonEnvelopeFor('Texas', 'USC', 'Texas edges USC.'),
      )

      renderHomePage(TEXAS_USC_LINK, { strict: true })

      expect(await screen.findByText('Texas edges USC.')).toBeInTheDocument()
      expect(screen.getByLabelText(/your team/i)).toHaveValue('Texas')
      expect(window.localStorage.getItem('myTeamIsBetter.userTeam')).toBeNull()
    })

    it('leaves a different saved team untouched, too', async () => {
      window.localStorage.setItem('myTeamIsBetter.userTeam', 'USC')
      mockedFetchCompare.mockResolvedValue(
        comparisonEnvelopeFor('Texas', 'USC', 'Texas edges USC.'),
      )

      renderHomePage(TEXAS_USC_LINK, { strict: true })

      expect(await screen.findByText('Texas edges USC.')).toBeInTheDocument()
      expect(screen.getByLabelText(/your team/i)).toHaveValue('Texas')
      expect(window.localStorage.getItem('myTeamIsBetter.userTeam')).toBe('USC')
    })

    it.each([
      ['no params at all', '/'],
      [
        'a compare link missing b',
        '/?q=compare&sport=cfb&year=2005&engine=elo&a=Texas&for=Texas',
      ],
      ['an unknown engine', '/?q=champion&sport=cfb&year=2005&engine=massey'],
      [
        'a non-integer year',
        '/?q=champion&sport=cfb&year=2005.5&engine=keener',
      ],
    ])(
      'asks nothing and shows the ordinary empty page for %s',
      async (_description, entry) => {
        renderHomePage(entry, { strict: true })

        await waitForDefaultYear()
        await expectThroughout(() => {
          expect(mockedFetchChampion).not.toHaveBeenCalled()
          expect(mockedFetchTeamCase).not.toHaveBeenCalled()
          expect(mockedFetchCompare).not.toHaveBeenCalled()
        })
        expect(screen.queryByRole('article')).not.toBeInTheDocument()
        expect(screen.getByLabelText(/what do you want to know/i)).toHaveValue(
          'champion',
        )
      },
    )

    it('offers to share a verdict asked through the form, as a link to that exact question', async () => {
      const user = userEvent.setup()
      mockedFetchChampion.mockResolvedValue(
        envelopeFor('Texas', 'Texas, full stop.'),
      )

      renderHomePage()
      await waitForDefaultYear()
      await user.clear(screen.getByLabelText(/year/i))
      await user.type(screen.getByLabelText(/year/i), '2005')
      // Not in the catalog, so a stale-team notice appears -- which is why
      // the field is not queried again by label below.
      await user.type(screen.getByLabelText(/your team/i), 'Texas A&M')
      await user.click(screen.getByRole('button', { name: /get the verdict/i }))
      expect(await screen.findByText('Texas, full stop.')).toBeInTheDocument()

      // After `userEvent.setup()`, which installs its own clipboard stub.
      const writeText = vi
        .fn<(text: string) => Promise<void>>()
        .mockResolvedValue(undefined)
      Object.defineProperty(window.navigator, 'clipboard', {
        value: { writeText },
        configurable: true,
        writable: true,
      })
      await user.click(
        screen.getByRole('button', { name: 'Share this verdict' }),
      )

      await waitFor(() =>
        expect(writeText).toHaveBeenCalledWith(
          `${window.location.origin}/?q=champion&sport=cfb&year=2005&engine=keener&for=Texas+A%26M`,
        ),
      )
      expect(await screen.findByText('Link copied')).toBeInTheDocument()
    })

    it('keeps the address bar on the share link of the question just asked, replacing history rather than pushing', async () => {
      const user = userEvent.setup()
      mockedFetchChampion.mockResolvedValue(
        envelopeFor('Texas', 'Texas, full stop.'),
      )

      renderHomePage()
      await waitForDefaultYear()
      await user.clear(screen.getByLabelText(/year/i))
      await user.type(screen.getByLabelText(/year/i), '2005')
      await user.click(screen.getByRole('button', { name: /get the verdict/i }))

      await waitFor(() =>
        expect(screen.getByTestId('location-search').textContent).toBe(
          '?q=champion&sport=cfb&year=2005&engine=keener',
        ),
      )
      expect(screen.getByTestId('navigation-type')).toHaveTextContent('REPLACE')
      expect(await screen.findByText('Texas, full stop.')).toBeInTheDocument()
    })

    it("mounts the form once on a link landing, so its first catalog requests already use the link's league and engine", async () => {
      mockedFetchChampion.mockResolvedValue(
        envelopeFor('Kansas City Chiefs', 'Chiefs, easy.'),
      )

      renderHomePage('/?q=champion&sport=nfl&year=2018&engine=elo', {
        strict: true,
      })

      expect(await screen.findByText('Chiefs, easy.')).toBeInTheDocument()
      expect(mockedFetchYears.mock.calls[0]).toEqual(['nfl', 'elo'])
      expect(mockedFetchTeams.mock.calls[0]).toEqual(['nfl', 'elo', 2018])
      // No request ever went out for the defaults (College, Keener) first.
      expect(
        mockedFetchYears.mock.calls.every(
          ([sport, method]) => sport === 'nfl' && method === 'elo',
        ),
      ).toBe(true)
      expect(
        mockedFetchTeams.mock.calls.every(
          ([sport, method]) => sport === 'nfl' && method === 'elo',
        ),
      ).toBe(true)
      expect(mockedFetchChampion).toHaveBeenCalledTimes(1)
    })

    /**
     * Issue #184 review (G3): a link's "for" team is never the visitor's, so
     * clearing it before they edit the field must leave their saved team.
     */
    it.each([
      [
        'the stale-team notice\'s "Clear this team"',
        async (user: ReturnType<typeof userEvent.setup>) => {
          await user.click(
            await screen.findByRole('button', { name: 'Clear this team' }),
          )
        },
      ],
      [
        'a league switch',
        async (user: ReturnType<typeof userEvent.setup>) => {
          await user.click(screen.getByRole('radio', { name: /nfl/i }))
        },
      ],
    ])(
      "never deletes the visitor's saved team through %s after a link landing",
      async (_description, clearTheTeam) => {
        window.localStorage.setItem('myTeamIsBetter.userTeam', 'USC')
        const user = userEvent.setup()
        mockedFetchCompare.mockResolvedValue(
          comparisonEnvelopeFor('Texas', 'USC', 'Texas edges USC.'),
        )

        // Gonzaga is not in this file's team catalog, so the notice shows.
        renderHomePage(
          '/?q=compare&sport=cfb&year=2005&engine=elo&a=Texas&b=USC&for=Gonzaga',
          { strict: true },
        )
        expect(await screen.findByText('Texas edges USC.')).toBeInTheDocument()
        await screen.findByRole('button', { name: 'Clear this team' })

        await clearTheTeam(user)

        expect(screen.getByLabelText(/your team/i)).toHaveValue('')
        expect(window.localStorage.getItem('myTeamIsBetter.userTeam')).toBe(
          'USC',
        )
      },
    )

    it("re-asks a pill correction after a link landing with the link's user team, while the remounted field shows the visitor's saved team", async () => {
      window.localStorage.setItem('myTeamIsBetter.userTeam', 'USC')
      const user = userEvent.setup()
      mockedFetchCompare
        .mockRejectedValueOnce(AMBIGUOUS_TEXAS_ST)
        .mockResolvedValueOnce(
          comparisonEnvelopeFor('Texas State', 'USC', 'Texas State, somehow.'),
        )

      renderHomePage(AMBIGUOUS_LINK, { strict: true })
      await user.click(
        await screen.findByRole('button', { name: 'Texas State' }),
      )

      expect(
        await screen.findByText('Texas State, somehow.'),
      ).toBeInTheDocument()
      expect(mockedFetchCompare).toHaveBeenCalledTimes(2)
      // The pill re-asks the question as it was asked (issue #38), so the
      // request still carries the link's team.
      expect(mockedFetchCompare).toHaveBeenLastCalledWith({
        year: 2005,
        team_a: 'Texas State',
        team_b: 'USC',
        user_team: 'Texas',
        sport: 'cfb',
        method: 'elo',
      })
      expect(screen.getByLabelText(/team a/i)).toHaveValue('Texas State')
      // The accepted edge case: a correction remounts the form the ordinary
      // way, re-reading the saved team, and the link never wrote over it.
      expect(screen.getByLabelText(/your team/i)).toHaveValue('USC')
      expect(window.localStorage.getItem('myTeamIsBetter.userTeam')).toBe('USC')
      expect(screen.getByTestId('location-search').textContent).toBe(
        '?q=compare&sport=cfb&year=2005&engine=elo&a=Texas+State&b=USC&for=Texas',
      )
    })
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
        elo_ledger: null,
        games: [],
        quality_wins: [],
        worst_loss: null,
      },
      narration: { text: 'Texas, full stop.', contested: false, cached: false },
    })

    renderHomePage()
    await waitForDefaultYear()
    await user.clear(screen.getByLabelText(/year/i))
    await user.type(screen.getByLabelText(/year/i), '2005')
    await user.click(screen.getByRole('button', { name: /get the verdict/i }))

    expect(await screen.findByText('Texas, full stop.')).toBeInTheDocument()
    expect(mockedFetchChampion).toHaveBeenCalledWith({
      year: 2005,
      user_team: null,
      sport: 'cfb',
      method: 'keener',
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
          elo_ledger: null,
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

    renderHomePage()
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
      method: 'keener',
    })
  })

  it('renders a generic failure state on a network error', async () => {
    const user = userEvent.setup()
    mockedFetchChampion.mockRejectedValue(
      new VerdictNetworkError('Could not reach the API.'),
    )

    renderHomePage()
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

    renderHomePage()
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

  describe('the Engine toggle (issue #154)', () => {
    function eloRadio() {
      return screen.getByRole('radio', { name: 'Elo (second opinion)' })
    }

    it.each([
      {
        questionType: 'champion' as const,
        fill: async () => {},
        assertCalled: () =>
          expect(mockedFetchChampion).toHaveBeenCalledWith({
            year: 2005,
            user_team: null,
            sport: 'cfb',
            method: 'elo',
          }),
      },
      {
        questionType: 'team_case' as const,
        fill: async (user: ReturnType<typeof userEvent.setup>) => {
          await user.type(screen.getByLabelText(/^team$/i), 'USC')
        },
        assertCalled: () =>
          expect(mockedFetchTeamCase).toHaveBeenCalledWith({
            year: 2005,
            team: 'USC',
            user_team: null,
            sport: 'cfb',
            method: 'elo',
          }),
      },
      {
        questionType: 'compare' as const,
        fill: async (user: ReturnType<typeof userEvent.setup>) => {
          await user.type(screen.getByLabelText(/team a/i), 'Texas')
          await user.type(screen.getByLabelText(/team b/i), 'USC')
        },
        assertCalled: () =>
          expect(mockedFetchCompare).toHaveBeenCalledWith({
            year: 2005,
            team_a: 'Texas',
            team_b: 'USC',
            user_team: null,
            sport: 'cfb',
            method: 'elo',
          }),
      },
    ])(
      'sends method "elo" in the $questionType request',
      async ({ questionType, fill, assertCalled }) => {
        const user = userEvent.setup()
        // Never settles: only the request body is under test.
        mockedFetchChampion.mockReturnValue(new Promise(() => {}))
        mockedFetchTeamCase.mockReturnValue(new Promise(() => {}))
        mockedFetchCompare.mockReturnValue(new Promise(() => {}))

        renderHomePage()
        await user.selectOptions(
          screen.getByLabelText(/what do you want to know/i),
          questionType,
        )
        await waitForDefaultYear()
        await user.click(eloRadio())
        await waitForDefaultYear()
        await user.clear(screen.getByLabelText(/year/i))
        await user.type(screen.getByLabelText(/year/i), '2005')
        await fill(user)
        await user.click(
          screen.getByRole('button', { name: /get the verdict/i }),
        )

        await waitFor(assertCalled)
      },
    )

    it('keeps the selected engine across a pill correction: the corrected request and the remounted form both say Elo', async () => {
      const user = userEvent.setup()
      mockedFetchChampion
        .mockRejectedValueOnce(UNKNOWN_YEAR_ERROR)
        .mockResolvedValueOnce(envelopeFor('Texas', 'Texas, full stop.'))

      renderHomePage()
      await waitForDefaultYear()
      await user.click(eloRadio())
      const submit = screen.getByRole('button', { name: /get the verdict/i })
      await waitFor(() => expect(submit).not.toBeDisabled())
      await user.click(submit)

      await user.click(
        await screen.findByRole('button', { name: String(CORRECTED_YEAR) }),
      )

      expect(await screen.findByText('Texas, full stop.')).toBeInTheDocument()
      expect(mockedFetchChampion).toHaveBeenLastCalledWith({
        year: CORRECTED_YEAR,
        user_team: null,
        sport: 'cfb',
        method: 'elo',
      })
      expect(eloRadio()).toBeChecked()
    })

    it('flipping the toggle neither re-asks nor clears the verdict on screen', async () => {
      const user = userEvent.setup()
      mockedFetchChampion.mockResolvedValue(
        envelopeFor('Texas', 'Texas, full stop.'),
      )

      renderHomePage()
      const submit = screen.getByRole('button', { name: /get the verdict/i })
      await waitFor(() => expect(submit).not.toBeDisabled())
      await user.click(submit)
      expect(await screen.findByText('Texas, full stop.')).toBeInTheDocument()

      await user.click(eloRadio())

      await expectThroughout(() => {
        expect(screen.getByText('Texas, full stop.')).toBeInTheDocument()
        expect(screen.getByText('Engine: Keener (default)')).toBeInTheDocument()
      })
      expect(mockedFetchChampion).toHaveBeenCalledTimes(1)
      expect(mockedFetchTeamCase).not.toHaveBeenCalled()
      expect(mockedFetchCompare).not.toHaveBeenCalled()
    })
  })

  describe('pill corrections update the visible form (issue #38)', () => {
    it('updates the Year input, not just the verdict, when a year pill is picked', async () => {
      const user = userEvent.setup()
      mockedFetchChampion
        .mockRejectedValueOnce(UNKNOWN_YEAR_ERROR)
        .mockResolvedValueOnce(envelopeFor('Texas', 'Texas, full stop.'))

      renderHomePage()
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
        method: 'keener',
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

      renderHomePage()
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

      renderHomePage()
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
          method: 'keener',
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

      renderHomePage()
      await user.click(screen.getByRole('radio', { name: /nfl/i }))
      // Wait for the NFL catalog's newest season to fill the Year field
      // (issue #136) -- until then the submit button is disabled.
      const submit = screen.getByRole('button', { name: /get the verdict/i })
      await waitFor(() => expect(submit).not.toBeDisabled())
      await user.click(submit)

      // Typed after the failed submission, so it was never part of it.
      await user.type(screen.getByLabelText(/your team/i), 'Bengals')

      // 2005, not 2018: the corrected year must differ from the catalog's
      // newest season, which the remounted form would default to on its own
      // -- a pill year equal to it could not show whether the correction
      // reached the form at all.
      await user.click(
        await screen.findByRole('button', { name: String(CORRECTED_YEAR) }),
      )

      expect(await screen.findByText('Texas, full stop.')).toBeInTheDocument()
      expect(screen.getByLabelText(/year/i)).toHaveValue(CORRECTED_YEAR)
      expect(screen.getByRole('radio', { name: /nfl/i })).toBeChecked()
      expect(screen.getByLabelText(/your team/i)).toHaveValue('Bengals')
      // The pill re-asks *the question that was asked*, with one field
      // corrected -- not a different question assembled from edits made
      // after the submit button was pressed. So the re-ask carries the
      // submitted `user_team` (none), while the field keeps what the user
      // has since typed for their next submission.
      expect(mockedFetchChampion).toHaveBeenLastCalledWith({
        year: CORRECTED_YEAR,
        user_team: null,
        sport: 'nfl',
        method: 'keener',
      })
    })

    /**
     * Issue #101: a team-catalog request genuinely in flight at the moment a
     * correction pill is clicked. The test this replaced resolved a pending
     * promise "across" the correction with *no* request outstanding at the
     * click, and its promise was then consumed by the remounted form's own
     * first fetch -- it could not fail for the reason it named.
     *
     * What this does prove: the request is outstanding at the click, and its
     * late response does not reach the corrected form -- no "No teams found
     * for 2004" hint, no year other than the corrected one. The precondition
     * is the call record (2004 was the last team-list request before the
     * click) together with a pending-promise probe on the promise the fixture
     * handed out for it; the probe guards the fixture, not production code.
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
      const held: { promise?: Promise<TeamsOut>; release: () => void } = {
        release: () => {},
      }
      mockedFetchTeams.mockImplementation((_sport, _method, year) => {
        if (year !== IN_FLIGHT_YEAR) {
          return Promise.resolve(TEAMS)
        }
        held.promise = new Promise<TeamsOut>((resolvePromise) => {
          // Empty, so a response that leaked onto the corrected form would
          // show up as the year-scoped empty hint.
          held.release = () => resolvePromise({ teams: [], team_details: [] })
        })
        return held.promise
      })

      renderHomePage()
      const submit = screen.getByRole('button', { name: /get the verdict/i })
      await waitFor(() => expect(submit).not.toBeDisabled())
      await user.click(submit)
      // Not the newest catalog season (2018), which the remounted form would
      // default to by itself -- see the previous test.
      const pill = await screen.findByRole('button', {
        name: String(CORRECTED_YEAR),
      })

      // An edit made after the failed submission, allowed to settle past the
      // form's debounce so its team-list request actually goes out.
      await user.clear(screen.getByLabelText(/year/i))
      await user.type(screen.getByLabelText(/year/i), String(IN_FLIGHT_YEAR))
      await waitFor(
        () =>
          expect(mockedFetchTeams).toHaveBeenLastCalledWith(
            'cfb',
            'keener',
            IN_FLIGHT_YEAR,
          ),
        { timeout: YEAR_DEBOUNCE_MS * 5 },
      )
      const callsBeforeCorrection = mockedFetchTeams.mock.calls.length
      const inFlight = held.promise
      if (inFlight === undefined) {
        throw new Error('the in-flight team-list request never went out')
      }
      expect(await hasSettled(inFlight)).toBe(false)

      await user.click(pill)

      expect(await screen.findByText('Texas, full stop.')).toBeInTheDocument()
      // The corrected form issued its own request, for the corrected year,
      // rather than inheriting the outstanding one.
      await waitFor(() =>
        expect(
          mockedFetchTeams.mock.calls.slice(callsBeforeCorrection),
        ).toContainEqual(['cfb', 'keener', CORRECTED_YEAR]),
      )

      held.release()
      expect(await hasSettled(inFlight)).toBe(true)

      await expectThroughout(() => {
        expect(screen.getByLabelText(/year/i)).toHaveValue(CORRECTED_YEAR)
        expect(
          screen.queryByText(/no teams found for/i),
        ).not.toBeInTheDocument()
      })
      expect(mockedFetchChampion).toHaveBeenLastCalledWith({
        year: CORRECTED_YEAR,
        user_team: null,
        sport: 'cfb',
        method: 'keener',
      })
    })
  })
})
