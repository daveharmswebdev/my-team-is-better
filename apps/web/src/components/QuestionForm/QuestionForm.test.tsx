import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { SPORTS } from '../../lib/api/types'
import type { Method, Sport, TeamDetail, TeamsOut } from '../../lib/api/types'
import { QuestionForm, YEAR_DEBOUNCE_MS } from './QuestionForm'

vi.mock('../../lib/api/client', async () => {
  const actual = await vi.importActual<typeof import('../../lib/api/client')>(
    '../../lib/api/client',
  )
  return {
    ...actual,
    fetchYears: vi.fn(),
    fetchTeams: vi.fn(),
  }
})

import { fetchTeams, fetchYears } from '../../lib/api/client'

const mockedFetchYears = vi.mocked(fetchYears)
const mockedFetchTeams = vi.mocked(fetchTeams)

/**
 * The year the form defaults to under the `beforeEach` catalog: the newest
 * season `/api/years` reports (issue #136), never the calendar year.
 */
const NEWEST_DEFAULT_YEAR = 2006

/** Newest season in `stubSportScopedTeams`' NFL catalog. */
const NEWEST_NFL_YEAR = 2022

const CFB_DETAILS: TeamDetail[] = [
  { name: 'Texas', mascot: 'Longhorns', aliases: ['TEX'] },
  { name: 'USC', mascot: 'Trojans', aliases: ['Southern California'] },
]

const NFL_DETAILS: TeamDetail[] = [
  { name: 'New England Patriots', mascot: null, aliases: ['NE'] },
  { name: 'Kansas City Chiefs', mascot: null, aliases: ['KC'] },
]

function teamsOut(details: TeamDetail[]): TeamsOut {
  return { teams: details.map((detail) => detail.name), team_details: details }
}

/** Inclusive integer range -- catalogs read like the real `/api/years`. */
function range(from: number, to: number): number[] {
  return Array.from({ length: to - from + 1 }, (_, index) => from + index)
}

/** Serves a different `/api/years` catalog per league. */
function stubLeagueYears(cfbYears: number[], nflYears: number[]) {
  mockedFetchYears.mockImplementation((sport?: Sport) =>
    Promise.resolve({ years: sport === 'nfl' ? nflYears : cfbYears }),
  )
}

/** Serves sport-scoped team details, so a league-scoping assertion has
 * something to actually scope against. */
function stubSportScopedTeams() {
  mockedFetchTeams.mockImplementation((sport?: Sport) =>
    Promise.resolve(teamsOut(sport === 'nfl' ? NFL_DETAILS : CFB_DETAILS)),
  )
  stubLeagueYears([2004, 2005, 2006], [2021, NEWEST_NFL_YEAR])
}

/**
 * The open suggestion list, scoped so option queries can't collide with the
 * question-type `<select>`'s own `role="option"` children (or the Year
 * `<datalist>`'s), which is exactly what a bare `getByRole('option')` does.
 */
function suggestions() {
  return within(screen.getByRole('listbox'))
}

/** Waits out the initial (immediate, undebounced) catalog load. */
async function waitForInitialCatalog() {
  await waitFor(() => expect(mockedFetchTeams).toHaveBeenCalled())
}

/**
 * Waits for the untouched Year field to settle on the catalog's newest
 * season *and* for the team refetch that settling triggers. Tests that count
 * `fetchTeams` calls wait on this first, so a default landing mid-assertion
 * can't be mistaken for a request the assertion caused.
 */
async function waitForDefaultYear(year = NEWEST_DEFAULT_YEAR) {
  await waitFor(() => expect(screen.getByLabelText(/year/i)).toHaveValue(year))
  await waitFor(() =>
    expect(mockedFetchTeams).toHaveBeenCalledWith('cfb', 'keener', year),
  )
}

function submitButton() {
  return screen.getByRole('button', { name: /get the verdict/i })
}

/** Any issue #100 stale-team flag, for any team, season or league. */
const ANY_STALE_NOTICE = /isn't in the .* team list/i

/**
 * The issue #100 flag copy, as a matcher. Deliberately asserts on the *scope*
 * words too (season + league), because "we stopped recognising this" is only
 * actionable if it says which season and which league stopped recognising it.
 */
function staleNotice(team: string, scope: string): RegExp {
  return new RegExp(`${team}.*isn't in the ${scope} team list`, 'i')
}

const ALABAMA: TeamDetail = {
  name: 'Alabama',
  mascot: 'Crimson Tide',
  aliases: [],
}

const NOT_A_YEAR_MESSAGE = 'Enter the season as a year, e.g. 2025.'
const TEAM_LIST_FAILED = /couldn't load the team list/i

/**
 * Lets every already-settled promise continuation run -- including an
 * effect's `await fetchTeams(...)` resuming and calling `setState` -- inside
 * `act`, so an assertion made afterwards sees whatever that continuation did.
 * A macrotask, not a single microtask: the continuation is several
 * microtasks deep.
 */
async function flushSettledRequests() {
  await act(async () => {
    await new Promise((resolveWait) => setTimeout(resolveWait, 0))
  })
}

/**
 * Whether `promise` has settled yet, read off the promise itself (a reaction
 * attached to it) rather than a flag the test flips in its own release
 * function -- so a fixture that hands out an already-settled promise fails
 * the check instead of passing it. An already-settled promise's reaction
 * beats a zero-delay timer; a pending one loses to it.
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
 * Asserts `assertion` holds continuously for `windowMs`, re-checking every
 * 20ms. A single zero-delay flush followed by an absence check only catches
 * a stale response that lands directly behind its promise; one deferred by
 * any timer would arrive after the check and pass it. Two debounce intervals
 * outlast anything `QuestionForm` schedules itself.
 */
async function expectThroughout(
  assertion: () => void,
  windowMs = YEAR_DEBOUNCE_MS * 2,
) {
  const deadline = Date.now() + windowMs
  do {
    assertion()
    await act(async () => {
      await new Promise((resolveWait) => setTimeout(resolveWait, 20))
    })
  } while (Date.now() < deadline)
  assertion()
}

/** Every `year` `fetchTeams` has been called with that is not a whole number. */
function nonIntegerTeamFetchYears(): unknown[] {
  return mockedFetchTeams.mock.calls
    .map(([, , year]) => year)
    .filter((year) => year !== undefined && !Number.isInteger(year))
}

/**
 * `/api/teams` as `apps/api` really serves it: `year` is declared `int`, so a
 * non-integer one is a 422, which the client surfaces as a thrown error --
 * and the form as "Couldn't load the team list". A mock that happily resolved
 * `2018.5` could not represent the failure these tests are about.
 */
function stubTeamsRejectingNonIntegerYears() {
  mockedFetchTeams.mockImplementation(
    (_sport?: Sport, _method?: Method, year?: number) =>
      year !== undefined && !Number.isInteger(year)
        ? Promise.reject(new Error('422: year is not an integer'))
        : Promise.resolve(teamsOut(CFB_DETAILS)),
  )
}

describe('QuestionForm', () => {
  beforeEach(() => {
    window.localStorage.clear()
    mockedFetchYears.mockReset()
    mockedFetchTeams.mockReset()
    mockedFetchYears.mockResolvedValue({ years: [2004, 2005, 2006] })
    mockedFetchTeams.mockResolvedValue(teamsOut(CFB_DETAILS))
  })
  afterEach(() => {
    window.localStorage.clear()
  })

  it('shows only the year field for the "champion" question type by default', () => {
    render(<QuestionForm onSubmit={vi.fn()} />)

    expect(screen.getByLabelText(/year/i)).toBeInTheDocument()
    expect(screen.queryByLabelText(/^team$/i)).not.toBeInTheDocument()
    expect(screen.queryByLabelText(/team a/i)).not.toBeInTheDocument()
    expect(screen.queryByLabelText(/team b/i)).not.toBeInTheDocument()
  })

  it('shows the team field when switching to "team case"', async () => {
    const user = userEvent.setup()
    render(<QuestionForm onSubmit={vi.fn()} />)

    await user.selectOptions(
      screen.getByLabelText(/what do you want to know/i),
      'team_case',
    )

    expect(screen.getByLabelText(/^team$/i)).toBeInTheDocument()
    expect(screen.queryByLabelText(/team a/i)).not.toBeInTheDocument()
  })

  it('shows team A / team B fields when switching to "compare"', async () => {
    const user = userEvent.setup()
    render(<QuestionForm onSubmit={vi.fn()} />)

    await user.selectOptions(
      screen.getByLabelText(/what do you want to know/i),
      'compare',
    )

    expect(screen.getByLabelText(/team a/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/team b/i)).toBeInTheDocument()
    expect(screen.queryByLabelText(/^team$/i)).not.toBeInTheDocument()
  })

  it('submits a champion question with the right shape', async () => {
    const user = userEvent.setup()
    const onSubmit = vi.fn()
    render(<QuestionForm onSubmit={onSubmit} />)
    // Let the catalog default land first -- otherwise it can arrive between
    // the clear and the typing, and the typed digits append to it (#136).
    await waitForDefaultYear()

    await user.clear(screen.getByLabelText(/year/i))
    await user.type(screen.getByLabelText(/year/i), '2005')
    await user.click(screen.getByRole('button', { name: /get the verdict/i }))

    expect(onSubmit).toHaveBeenCalledWith({
      questionType: 'champion',
      year: 2005,
      userTeam: null,
      sport: 'cfb',
      method: 'keener',
    })
  })

  it('submits a team-case question with the right shape', async () => {
    const user = userEvent.setup()
    const onSubmit = vi.fn()
    render(<QuestionForm onSubmit={onSubmit} />)
    // Let the catalog default land first -- otherwise it can arrive between
    // the clear and the typing, and the typed digits append to it (#136).
    await waitForDefaultYear()

    await user.selectOptions(
      screen.getByLabelText(/what do you want to know/i),
      'team_case',
    )
    await user.clear(screen.getByLabelText(/year/i))
    await user.type(screen.getByLabelText(/year/i), '2005')
    await user.type(screen.getByLabelText(/^team$/i), 'Texas')
    await user.click(screen.getByRole('button', { name: /get the verdict/i }))

    expect(onSubmit).toHaveBeenCalledWith({
      questionType: 'team_case',
      year: 2005,
      team: 'Texas',
      userTeam: null,
      sport: 'cfb',
      method: 'keener',
    })
  })

  it('submits a compare question with the right shape, including a persisted user team', async () => {
    const user = userEvent.setup()
    const onSubmit = vi.fn()
    render(<QuestionForm onSubmit={onSubmit} />)
    // Let the catalog default land first -- otherwise it can arrive between
    // the clear and the typing, and the typed digits append to it (#136).
    await waitForDefaultYear()

    await user.selectOptions(
      screen.getByLabelText(/what do you want to know/i),
      'compare',
    )
    await user.clear(screen.getByLabelText(/year/i))
    await user.type(screen.getByLabelText(/year/i), '2005')
    await user.type(screen.getByLabelText(/team a/i), 'Texas')
    await user.type(screen.getByLabelText(/team b/i), 'USC')
    await user.type(screen.getByLabelText(/your team/i), 'Texas')
    await user.click(screen.getByRole('button', { name: /get the verdict/i }))

    expect(onSubmit).toHaveBeenCalledWith({
      questionType: 'compare',
      year: 2005,
      teamA: 'Texas',
      teamB: 'USC',
      userTeam: 'Texas',
      sport: 'cfb',
      method: 'keener',
    })
    expect(window.localStorage.getItem('myTeamIsBetter.userTeam')).toBe('Texas')
  })

  it('disables the submit button while a submission is in flight', () => {
    render(<QuestionForm onSubmit={vi.fn()} isSubmitting />)

    expect(screen.getByRole('button')).toBeDisabled()
  })

  it('prefills the "your team" field from localStorage on mount', () => {
    window.localStorage.setItem('myTeamIsBetter.userTeam', 'Ohio State')

    render(<QuestionForm onSubmit={vi.fn()} />)

    expect(screen.getByLabelText(/your team/i)).toHaveValue('Ohio State')
  })

  it('question type select only exposes the three in-scope options', () => {
    render(<QuestionForm onSubmit={vi.fn()} />)

    const select = screen.getByLabelText(/what do you want to know/i)
    const options = within(select).getAllByRole('option')
    expect(options).toHaveLength(3)
  })

  describe('catalog-backed year suggestions', () => {
    it('fetches the catalog on mount and offers fetched years as datalist suggestions', async () => {
      render(<QuestionForm onSubmit={vi.fn()} />)

      await waitFor(() => expect(mockedFetchYears).toHaveBeenCalled())
      const yearInput = screen.getByLabelText(/year/i)
      await waitFor(() => expect(yearInput.getAttribute('list')).toBeTruthy())
      const yearList = document.getElementById(
        yearInput.getAttribute('list') ?? '',
      )
      expect(yearList).not.toBeNull()
      const yearOptions = within(yearList as HTMLElement).getAllByRole(
        'option',
        { hidden: true },
      )
      expect(yearOptions.map((option) => option.getAttribute('value'))).toEqual(
        ['2004', '2005', '2006'],
      )
    })

    it('does not block a typed year while the catalog fetch is still in flight', () => {
      mockedFetchYears.mockReturnValue(new Promise(() => {}))
      mockedFetchTeams.mockReturnValue(new Promise(() => {}))

      render(<QuestionForm onSubmit={vi.fn()} />)

      // No catalog, so no default to offer yet -- and never a calendar-year
      // guess in its place (issue #136).
      const yearInput = screen.getByLabelText(/year/i)
      expect(yearInput).toHaveValue(null)
      expect(submitButton()).toBeDisabled()

      fireEvent.change(yearInput, { target: { value: '2005' } })

      // With nothing to range-check against, a numeric year is enough.
      expect(submitButton()).not.toBeDisabled()
    })
  })

  describe('year default and validation (issue #136)', () => {
    it('defaults the year to the newest season in the College catalog, not the calendar year', async () => {
      mockedFetchYears.mockReturnValue(new Promise(() => {}))
      const { unmount } = render(<QuestionForm onSubmit={vi.fn()} />)
      // Before the catalog lands the field is empty, never a guess.
      expect(screen.getByLabelText(/year/i)).toHaveValue(null)
      unmount()

      mockedFetchYears.mockResolvedValue({ years: [2004, 2005, 2006] })
      render(<QuestionForm onSubmit={vi.fn()} />)

      await waitFor(() =>
        expect(screen.getByLabelText(/year/i)).toHaveValue(NEWEST_DEFAULT_YEAR),
      )
      expect(submitButton()).not.toBeDisabled()
    })

    it('defaults the year to the newest season in the NFL catalog', async () => {
      stubLeagueYears(range(1998, 2025), range(1999, 2019))
      render(<QuestionForm onSubmit={vi.fn()} initialSport="nfl" />)

      await waitFor(() =>
        expect(screen.getByLabelText(/year/i)).toHaveValue(2019),
      )
      expect(mockedFetchYears).toHaveBeenCalledWith('nfl', 'keener')
    })

    it('keeps an explicit initialYear even when the catalog has newer seasons', async () => {
      render(<QuestionForm onSubmit={vi.fn()} initialYear={2004} />)

      // The catalog has landed (it backs the datalist)...
      await waitFor(() =>
        expect(
          screen.getByLabelText(/year/i).getAttribute('list'),
        ).toBeTruthy(),
      )
      // ...and still did not overwrite the parent's year.
      expect(screen.getByLabelText(/year/i)).toHaveValue(2004)
    })

    it("moves an untouched default to the new league's newest season on a league switch", async () => {
      stubLeagueYears([2004, 2005, 2006], [2021, NEWEST_NFL_YEAR])
      const user = userEvent.setup()
      render(<QuestionForm onSubmit={vi.fn()} />)
      await waitFor(() =>
        expect(screen.getByLabelText(/year/i)).toHaveValue(NEWEST_DEFAULT_YEAR),
      )

      await user.click(screen.getByRole('radio', { name: /nfl/i }))

      await waitFor(() =>
        expect(screen.getByLabelText(/year/i)).toHaveValue(NEWEST_NFL_YEAR),
      )
    })

    it('keeps a year the user typed across a league switch', async () => {
      stubLeagueYears([2004, 2005, 2006], [2005, 2021, NEWEST_NFL_YEAR])
      const user = userEvent.setup()
      render(<QuestionForm onSubmit={vi.fn()} />)
      await waitForDefaultYear()

      await user.clear(screen.getByLabelText(/year/i))
      await user.type(screen.getByLabelText(/year/i), '2005')
      await user.click(screen.getByRole('radio', { name: /nfl/i }))

      // The NFL catalog has landed...
      expect(
        await screen.findByText(/seasons with data: 2005-2022/i),
      ).toBeInTheDocument()
      // ...and the typed year is untouched.
      expect(screen.getByLabelText(/year/i)).toHaveValue(2005)
    })

    it.each([
      {
        case: 'a year outside the catalog',
        catalog: [2004, 2005, 2006],
        typed: '2010',
        errorCopy: /no college football data for 2010/i,
        details: [/2004-2006/],
        validYear: '2005',
      },
      {
        case: 'a year inside a gap in the catalog',
        catalog: [2001, 2003],
        typed: '2002',
        errorCopy: /no college football data for 2002/i,
        details: [/2001-2003/, /gaps/i],
        validYear: '2001',
      },
    ])(
      'rejects $case: disabled submit, inline error, aria-invalid -- until a valid year clears it',
      async ({ catalog, typed, errorCopy, details, validYear }) => {
        mockedFetchYears.mockResolvedValue({ years: catalog })
        render(<QuestionForm onSubmit={vi.fn()} />)
        const yearInput = screen.getByLabelText(/year/i)
        await waitFor(() => expect(yearInput).toHaveValue(Math.max(...catalog)))

        fireEvent.change(yearInput, { target: { value: typed } })

        // The button reacts to the live value at once...
        expect(submitButton()).toBeDisabled()
        // ...but the message waits for typing to pause, so "2010" never
        // flashes an error at "2".
        expect(screen.queryByText(errorCopy)).not.toBeInTheDocument()

        const error = await screen.findByText(
          errorCopy,
          {},
          { timeout: YEAR_DEBOUNCE_MS * 5 },
        )
        for (const pattern of [errorCopy, ...details]) {
          expect(error).toHaveTextContent(pattern)
        }
        expect(yearInput).toHaveAttribute('aria-invalid', 'true')
        expect(error.id).not.toBe('')
        expect(yearInput.getAttribute('aria-describedby') ?? '').toContain(
          error.id,
        )
        expect(submitButton()).toBeDisabled()

        fireEvent.change(yearInput, { target: { value: validYear } })

        expect(screen.queryByText(errorCopy)).not.toBeInTheDocument()
        expect(yearInput).not.toHaveAttribute('aria-invalid', 'true')
        expect(submitButton()).not.toBeDisabled()
      },
    )

    it('disables submit for an empty year, without an error message', async () => {
      render(<QuestionForm onSubmit={vi.fn()} />)
      const yearInput = screen.getByLabelText(/year/i)
      await waitForDefaultYear()

      fireEvent.change(yearInput, { target: { value: '' } })

      expect(submitButton()).toBeDisabled()
      // Past the debounce: an empty field is explained by the disabled
      // button alone, not by an error.
      await new Promise((resolveWait) =>
        setTimeout(resolveWait, YEAR_DEBOUNCE_MS * 2),
      )
      expect(screen.queryByText(/no .* data for/i)).not.toBeInTheDocument()
      expect(yearInput).not.toHaveAttribute('aria-invalid', 'true')
      expect(submitButton()).toBeDisabled()
    })

    it('refuses to submit an invalid year even if the form is submitted directly', async () => {
      const onSubmit = vi.fn()
      render(<QuestionForm onSubmit={onSubmit} />)
      await waitForDefaultYear()

      fireEvent.change(screen.getByLabelText(/year/i), {
        target: { value: '2010' },
      })
      const form = submitButton().closest('form')
      expect(form).not.toBeNull()
      fireEvent.submit(form as HTMLFormElement)

      expect(onSubmit).not.toHaveBeenCalled()
    })

    it('revalidates on a league switch: 1998 is valid for College and not for the NFL', async () => {
      stubLeagueYears(range(1998, 2025), range(1999, 2025))
      const user = userEvent.setup()
      render(<QuestionForm onSubmit={vi.fn()} initialYear={1998} />)

      expect(
        await screen.findByText(/seasons with data: 1998-2025/i),
      ).toBeInTheDocument()
      expect(submitButton()).not.toBeDisabled()
      expect(screen.queryByText(/no .* data for/i)).not.toBeInTheDocument()

      await user.click(screen.getByRole('radio', { name: /nfl/i }))

      const error = await screen.findByText(
        /no NFL data for 1998/i,
        {},
        { timeout: YEAR_DEBOUNCE_MS * 5 },
      )
      expect(error).toHaveTextContent(/1999-2025/)
      expect(screen.getByLabelText(/year/i)).toHaveValue(1998)
      expect(screen.getByLabelText(/year/i)).toHaveAttribute(
        'aria-invalid',
        'true',
      )
      expect(submitButton()).toBeDisabled()
    })

    it('never lets a failed years fetch block a typed year', async () => {
      mockedFetchYears.mockRejectedValue(new Error('network down'))
      const user = userEvent.setup()
      const onSubmit = vi.fn()
      render(<QuestionForm onSubmit={onSubmit} />)

      expect(
        await screen.findByText(/couldn't load the list of available years/i),
      ).toBeInTheDocument()

      // Any whole four-digit year goes: there is no range to check it against.
      await user.type(screen.getByLabelText(/year/i), '1850')
      expect(submitButton()).not.toBeDisabled()
      await new Promise((resolveWait) =>
        setTimeout(resolveWait, YEAR_DEBOUNCE_MS * 2),
      )
      expect(screen.queryByText(/no .* data for/i)).not.toBeInTheDocument()

      await user.click(submitButton())
      expect(onSubmit).toHaveBeenCalledWith({
        questionType: 'champion',
        year: 1850,
        userTeam: null,
        sport: 'cfb',
        method: 'keener',
      })
    })

    it('never lets a league with no seasons ingested yet block a typed year', async () => {
      mockedFetchYears.mockResolvedValue({ years: [] })
      render(<QuestionForm onSubmit={vi.fn()} />)
      await waitFor(() =>
        expect(mockedFetchYears).toHaveBeenCalledWith('cfb', 'keener'),
      )
      // Let the resolved (empty) catalog land before typing against it.
      await new Promise((resolveWait) =>
        setTimeout(resolveWait, YEAR_DEBOUNCE_MS),
      )

      const yearInput = screen.getByLabelText(/year/i)
      // An empty catalog has no newest season to default to.
      expect(yearInput).toHaveValue(null)

      fireEvent.change(yearInput, { target: { value: '2005' } })

      // Like a failed fetch, an empty catalog has nothing to range-check
      // against, so any whole four-digit year goes and `unknown_year` is the
      // backstop.
      expect(submitButton()).not.toBeDisabled()
      await new Promise((resolveWait) =>
        setTimeout(resolveWait, YEAR_DEBOUNCE_MS * 2),
      )
      expect(screen.queryByText(/no .* data for/i)).not.toBeInTheDocument()
      expect(yearInput).not.toHaveAttribute('aria-invalid', 'true')
      expect(submitButton()).not.toBeDisabled()
    })
  })

  describe('a league switch clears every team field (issue #137)', () => {
    it('clears Team A, Team B and "your team" (and its stored value) on College -> NFL', async () => {
      stubSportScopedTeams()
      const user = userEvent.setup()
      render(<QuestionForm onSubmit={vi.fn()} initialQuestionType="compare" />)
      await waitForInitialCatalog()

      await user.type(screen.getByLabelText(/team a/i), 'Texas')
      await user.type(screen.getByLabelText(/team b/i), 'USC')
      await user.type(screen.getByLabelText(/your team/i), 'Texas')
      expect(window.localStorage.getItem('myTeamIsBetter.userTeam')).toBe(
        'Texas',
      )

      await user.click(screen.getByRole('radio', { name: /nfl/i }))

      expect(screen.getByLabelText(/team a/i)).toHaveValue('')
      expect(screen.getByLabelText(/team b/i)).toHaveValue('')
      expect(screen.getByLabelText(/your team/i)).toHaveValue('')
      expect(window.localStorage.getItem('myTeamIsBetter.userTeam')).toBeNull()

      // Once the NFL catalog has landed there is nothing left to flag.
      await waitFor(() =>
        expect(mockedFetchTeams).toHaveBeenLastCalledWith(
          'nfl',
          'keener',
          NEWEST_NFL_YEAR,
        ),
      )
      await waitFor(() =>
        expect(screen.getByLabelText(/your team/i)).toHaveAttribute(
          'placeholder',
          expect.stringMatching(/chiefs/i),
        ),
      )
      expect(screen.queryByText(ANY_STALE_NOTICE)).not.toBeInTheDocument()
    })

    it('clears the single team field of a team-case question', async () => {
      stubSportScopedTeams()
      const user = userEvent.setup()
      render(
        <QuestionForm
          onSubmit={vi.fn()}
          initialQuestionType="team_case"
          initialYear={2005}
          initialTeam="Texas"
        />,
      )
      await waitForInitialCatalog()

      await user.click(screen.getByRole('radio', { name: /nfl/i }))

      expect(screen.getByLabelText(/^team$/i)).toHaveValue('')
      await waitFor(() =>
        expect(mockedFetchTeams).toHaveBeenLastCalledWith(
          'nfl',
          'keener',
          2005,
        ),
      )
      expect(screen.queryByText(ANY_STALE_NOTICE)).not.toBeInTheDocument()
    })

    it('clears the team fields on NFL -> College too', async () => {
      stubSportScopedTeams()
      window.localStorage.setItem(
        'myTeamIsBetter.userTeam',
        'Kansas City Chiefs',
      )
      const user = userEvent.setup()
      render(
        <QuestionForm
          onSubmit={vi.fn()}
          initialQuestionType="compare"
          initialSport="nfl"
          initialTeamA="Kansas City Chiefs"
          initialTeamB="New England Patriots"
        />,
      )
      await waitForInitialCatalog()

      await user.click(screen.getByRole('radio', { name: /college/i }))

      expect(screen.getByLabelText(/team a/i)).toHaveValue('')
      expect(screen.getByLabelText(/team b/i)).toHaveValue('')
      expect(screen.getByLabelText(/your team/i)).toHaveValue('')
      expect(window.localStorage.getItem('myTeamIsBetter.userTeam')).toBeNull()
      await waitFor(() =>
        expect(mockedFetchTeams).toHaveBeenLastCalledWith(
          'cfb',
          'keener',
          NEWEST_DEFAULT_YEAR,
        ),
      )
      expect(screen.queryByText(ANY_STALE_NOTICE)).not.toBeInTheDocument()
    })

    it('keeps every team value when the already-selected league is clicked again', async () => {
      window.localStorage.setItem('myTeamIsBetter.userTeam', 'Texas')
      const user = userEvent.setup()
      render(
        <QuestionForm
          onSubmit={vi.fn()}
          initialQuestionType="compare"
          initialTeamA="Texas"
          initialTeamB="USC"
        />,
      )
      await waitForInitialCatalog()

      await user.click(screen.getByRole('radio', { name: /college/i }))

      expect(screen.getByLabelText(/team a/i)).toHaveValue('Texas')
      expect(screen.getByLabelText(/team b/i)).toHaveValue('USC')
      expect(screen.getByLabelText(/your team/i)).toHaveValue('Texas')
      expect(window.localStorage.getItem('myTeamIsBetter.userTeam')).toBe(
        'Texas',
      )
      expect(mockedFetchYears).toHaveBeenCalledTimes(1)
    })
  })

  describe('team typeahead (issue #80)', () => {
    it.each([
      ['champion', /your team/i],
      ['team_case', /^team$/i],
      ['compare', /team a/i],
    ] as const)(
      'gives the %s question type a working typeahead on its team fields',
      async (questionType, label) => {
        const user = userEvent.setup()
        render(<QuestionForm onSubmit={vi.fn()} />)
        await waitForInitialCatalog()

        await user.selectOptions(
          screen.getByLabelText(/what do you want to know/i),
          questionType,
        )

        const field = await screen.findByLabelText(label)
        await waitFor(() => expect(field).toHaveAttribute('role', 'combobox'))
        await user.type(field, 'Tex')

        await waitFor(() => expect(screen.getByRole('listbox')).toBeVisible())
        expect(
          suggestions().getByRole('option', { name: /Texas/ }),
        ).toBeInTheDocument()
      },
    )

    it('gives "your team" a typeahead even on the champion type, where it is the only team input', async () => {
      const user = userEvent.setup()
      render(<QuestionForm onSubmit={vi.fn()} />)
      await waitForInitialCatalog()

      // No other team field is rendered for this question type at all.
      expect(screen.queryByLabelText(/^team$/i)).not.toBeInTheDocument()
      expect(screen.queryByLabelText(/team a/i)).not.toBeInTheDocument()

      const userTeamField = screen.getByLabelText(/your team/i)
      await waitFor(() =>
        expect(userTeamField).toHaveAttribute('role', 'combobox'),
      )
      await user.type(userTeamField, 'Longhorns')

      await waitFor(() => expect(screen.getByRole('listbox')).toBeVisible())
      expect(
        suggestions().getByRole('option', { name: /Texas/ }),
      ).toBeInTheDocument()
    })

    it('scopes "your team" suggestions to the selected league', async () => {
      stubSportScopedTeams()
      const user = userEvent.setup()
      render(<QuestionForm onSubmit={vi.fn()} />)
      await waitForInitialCatalog()

      const userTeamField = screen.getByLabelText(/your team/i)
      await waitFor(() =>
        expect(userTeamField).toHaveAttribute('role', 'combobox'),
      )
      await user.type(userTeamField, 'Patriots')
      // No listbox at all: an NFL team is not on offer for a College question.
      expect(screen.queryByRole('listbox')).not.toBeInTheDocument()

      await user.click(screen.getByRole('radio', { name: /nfl/i }))
      await waitFor(() =>
        expect(mockedFetchTeams).toHaveBeenLastCalledWith(
          'nfl',
          'keener',
          NEWEST_NFL_YEAR,
        ),
      )
      // The switch cleared the field (issue #137), so ask again.
      await user.type(screen.getByLabelText(/your team/i), 'Patriots')

      await waitFor(() => expect(screen.getByRole('listbox')).toBeVisible())
      expect(
        suggestions().getByRole('option', { name: /New England Patriots/ }),
      ).toBeInTheDocument()
    })

    it('persists a "your team" suggestion picked from the list to localStorage', async () => {
      const user = userEvent.setup()
      render(<QuestionForm onSubmit={vi.fn()} />)
      await waitForInitialCatalog()

      const userTeamField = screen.getByLabelText(/your team/i)
      await waitFor(() =>
        expect(userTeamField).toHaveAttribute('role', 'combobox'),
      )
      await user.type(userTeamField, 'Longhorns')
      await waitFor(() => expect(screen.getByRole('listbox')).toBeVisible())
      await user.click(suggestions().getByRole('option', { name: /Texas/ }))

      // The canonical name, not the typed mascot.
      expect(screen.getByLabelText(/your team/i)).toHaveValue('Texas')
      expect(window.localStorage.getItem('myTeamIsBetter.userTeam')).toBe(
        'Texas',
      )
    })

    it('orders suggestions alphabetically by canonical name, not by API order', async () => {
      mockedFetchTeams.mockResolvedValue(
        teamsOut([
          { name: 'USC', mascot: 'Trojans', aliases: [] },
          { name: 'Auburn', mascot: 'Tigers', aliases: [] },
          { name: 'Texas', mascot: 'Longhorns', aliases: [] },
        ]),
      )
      const user = userEvent.setup()
      render(<QuestionForm onSubmit={vi.fn()} />)
      await waitForInitialCatalog()

      const userTeamField = screen.getByLabelText(/your team/i)
      await waitFor(() =>
        expect(userTeamField).toHaveAttribute('role', 'combobox'),
      )
      await user.click(userTeamField)

      await waitFor(() => expect(screen.getByRole('listbox')).toBeVisible())
      const options = suggestions().getAllByRole('option')
      expect(
        options.map((option) => option.textContent?.split(' · ')[0]),
      ).toEqual(['Auburn', 'Texas', 'USC'])
    })
  })

  describe('year-scoped team fetching (issue #80)', () => {
    it('scopes the team fetch to the default year once the catalog supplies it', async () => {
      render(<QuestionForm onSubmit={vi.fn()} />)

      await waitFor(() =>
        expect(mockedFetchTeams).toHaveBeenCalledWith(
          'cfb',
          'keener',
          NEWEST_DEFAULT_YEAR,
        ),
      )
      // /api/years is not year-scoped -- its request shape is untouched.
      expect(mockedFetchYears).toHaveBeenCalledWith('cfb', 'keener')
    })

    it('refetches the team list when the year changes', async () => {
      render(<QuestionForm onSubmit={vi.fn()} />)
      await waitForDefaultYear()
      mockedFetchTeams.mockClear()

      fireEvent.change(screen.getByLabelText(/year/i), {
        target: { value: '2005' },
      })

      await waitFor(() =>
        expect(mockedFetchTeams).toHaveBeenCalledWith('cfb', 'keener', 2005),
      )
    })

    it('debounces the year-driven refetch: typing "2010" issues one request, not four', async () => {
      render(<QuestionForm onSubmit={vi.fn()} />)
      await waitForDefaultYear()
      mockedFetchTeams.mockClear()

      // Synchronous `fireEvent`s, deliberately: this asserts on *how many*
      // requests a four-keystroke year costs, so the keystrokes must land
      // inside one debounce window without depending on how fast
      // `userEvent`'s inter-key awaits happen to run on the host.
      const yearInput = screen.getByLabelText(/year/i)
      for (const value of ['2', '20', '201', '2010']) {
        fireEvent.change(yearInput, { target: { value } })
      }
      expect(mockedFetchTeams).not.toHaveBeenCalled()

      await waitFor(() => expect(mockedFetchTeams).toHaveBeenCalledTimes(1), {
        timeout: YEAR_DEBOUNCE_MS * 5,
      })
      expect(mockedFetchTeams).toHaveBeenCalledWith('cfb', 'keener', 2010)
    })

    it('sends no year at all while the year input is empty', async () => {
      render(<QuestionForm onSubmit={vi.fn()} />)
      await waitForDefaultYear()
      mockedFetchTeams.mockClear()

      fireEvent.change(screen.getByLabelText(/year/i), {
        target: { value: '' },
      })

      await waitFor(() => expect(mockedFetchTeams).toHaveBeenCalledTimes(1))
      // `Number('')` is 0, a finite number -- an emptied input must still
      // ask for the whole per-sport list, not for year 0.
      expect(mockedFetchTeams).toHaveBeenCalledWith('cfb', 'keener', undefined)
    })

    it('refetches immediately (not debounced) when the league toggles', async () => {
      stubSportScopedTeams()
      const user = userEvent.setup()
      render(<QuestionForm onSubmit={vi.fn()} />)
      await waitForInitialCatalog()

      await user.click(screen.getByRole('radio', { name: /nfl/i }))

      await waitFor(() =>
        expect(mockedFetchTeams).toHaveBeenLastCalledWith(
          'nfl',
          'keener',
          NEWEST_NFL_YEAR,
        ),
      )
      expect(mockedFetchYears).toHaveBeenLastCalledWith('nfl', 'keener')
    })
  })

  describe('degraded catalog states (issue #80)', () => {
    it('leaves a usable plain input when the catalog fetch fails', async () => {
      mockedFetchYears.mockRejectedValue(new Error('network down'))
      mockedFetchTeams.mockRejectedValue(new Error('network down'))
      const user = userEvent.setup()
      const onSubmit = vi.fn()
      render(<QuestionForm onSubmit={onSubmit} />)

      await waitFor(() => expect(mockedFetchYears).toHaveBeenCalled())
      await waitFor(() =>
        expect(
          screen.getByText(/couldn't load the team list/i),
        ).toBeInTheDocument(),
      )

      const yearInput = screen.getByLabelText(/year/i)
      expect(yearInput.getAttribute('list')).toBeFalsy()

      // Plain input, not a combobox: no suggestions to reconcile.
      const userTeamField = screen.getByLabelText(/your team/i)
      expect(userTeamField).not.toHaveAttribute('role', 'combobox')

      await user.clear(yearInput)
      await user.type(yearInput, '2005')
      await user.type(userTeamField, 'Whatever FC')
      await user.click(screen.getByRole('button', { name: /get the verdict/i }))

      expect(onSubmit).toHaveBeenCalledWith({
        questionType: 'champion',
        year: 2005,
        userTeam: 'Whatever FC',
        sport: 'cfb',
        method: 'keener',
      })
    })

    it('reads an empty year-scoped list differently from a failed fetch', async () => {
      mockedFetchTeams.mockResolvedValue({ teams: [], team_details: [] })
      render(<QuestionForm onSubmit={vi.fn()} />)

      await waitForInitialCatalog()

      const emptyNote = await screen.findByText(
        new RegExp(`no teams .*${NEWEST_DEFAULT_YEAR}`, 'i'),
      )
      expect(emptyNote).toBeInTheDocument()
      expect(
        screen.queryByText(/couldn't load the team list/i),
      ).not.toBeInTheDocument()
    })

    it('still lets the form submit unvalidated input when the year-scoped list is empty', async () => {
      mockedFetchTeams.mockResolvedValue({ teams: [], team_details: [] })
      const user = userEvent.setup()
      const onSubmit = vi.fn()
      render(<QuestionForm onSubmit={onSubmit} />)
      await waitForDefaultYear()

      await user.clear(screen.getByLabelText(/year/i))
      await user.type(screen.getByLabelText(/year/i), '2005')
      await user.click(screen.getByRole('button', { name: /get the verdict/i }))

      expect(onSubmit).toHaveBeenCalledWith({
        questionType: 'champion',
        year: 2005,
        userTeam: null,
        sport: 'cfb',
        method: 'keener',
      })
    })
  })

  describe('stale team values across a scope change (issue #100)', () => {
    /**
     * Every clear affordance currently on screen. Queried by the shared
     * "Clear ..." accessible-name prefix rather than per-field, so these
     * assertions don't quietly pass by asking for a button that was renamed.
     */
    function clearButtons() {
      return screen.queryAllByRole('button', { name: /^Clear / })
    }

    /** Year-scoped teams: Texas is a 2005 team and nothing else. */
    function stubYearScopedTeams() {
      mockedFetchTeams.mockImplementation(
        (_sport?: Sport, _method?: Method, year?: number) =>
          Promise.resolve(
            teamsOut(
              year === 2005
                ? CFB_DETAILS
                : [{ name: 'Alabama', mascot: 'Crimson Tide', aliases: [] }],
            ),
          ),
      )
    }

    it('flags -- but keeps, and still submits -- a team that the newly entered season does not have', async () => {
      stubYearScopedTeams()
      // Both seasons have data, so the Year field itself is valid throughout
      // (issue #136) and only the team flag is under test.
      mockedFetchYears.mockResolvedValue({ years: [2005, 2018] })
      const user = userEvent.setup()
      const onSubmit = vi.fn()
      render(
        <QuestionForm
          onSubmit={onSubmit}
          initialQuestionType="team_case"
          initialYear={2005}
          initialTeam="Texas"
        />,
      )
      await waitFor(() =>
        expect(mockedFetchTeams).toHaveBeenCalledWith('cfb', 'keener', 2005),
      )
      expect(clearButtons()).toHaveLength(0)

      fireEvent.change(screen.getByLabelText(/year/i), {
        target: { value: '2018' },
      })
      await waitFor(
        () =>
          expect(mockedFetchTeams).toHaveBeenLastCalledWith(
            'cfb',
            'keener',
            2018,
          ),
        { timeout: YEAR_DEBOUNCE_MS * 5 },
      )

      expect(
        await screen.findByText(staleNotice('Texas', '2018 college football')),
      ).toBeInTheDocument()
      expect(screen.getByLabelText(/^team$/i)).toHaveValue('Texas')

      await user.click(screen.getByRole('button', { name: /get the verdict/i }))
      expect(onSubmit).toHaveBeenCalledWith({
        questionType: 'team_case',
        year: 2018,
        team: 'Texas',
        userTeam: null,
        sport: 'cfb',
        method: 'keener',
      })
    })

    it('clears the field, but only when the user asks it to', async () => {
      stubSportScopedTeams()
      const user = userEvent.setup()
      render(
        <QuestionForm
          onSubmit={vi.fn()}
          initialQuestionType="team_case"
          initialSport="nfl"
          initialYear={2005}
          initialTeam="Texas"
        />,
      )

      await user.click(
        await screen.findByRole('button', { name: 'Clear the team' }),
      )

      expect(screen.getByLabelText(/^team$/i)).toHaveValue('')
      expect(clearButtons()).toHaveLength(0)
    })

    it('flags each side of a compare question independently', async () => {
      stubYearScopedTeams()
      render(
        <QuestionForm
          onSubmit={vi.fn()}
          initialQuestionType="compare"
          initialYear={2018}
          initialTeamA="Alabama"
          initialTeamB="Texas"
        />,
      )

      expect(
        await screen.findByText(staleNotice('Texas', '2018 college football')),
      ).toBeInTheDocument()
      expect(
        screen.queryByText(staleNotice('Alabama', '2018 college football')),
      ).not.toBeInTheDocument()
      expect(clearButtons().map((button) => button.ariaLabel)).toEqual([
        'Clear the second team',
      ])
    })

    it('says nothing before the first catalog has landed', async () => {
      mockedFetchTeams.mockReturnValue(new Promise(() => {}))
      render(
        <QuestionForm
          onSubmit={vi.fn()}
          initialQuestionType="team_case"
          initialYear={2005}
          initialTeam="Whatever FC"
        />,
      )

      await waitForInitialCatalog()
      // "Not in the catalog" is meaningless before the catalog has landed.
      expect(clearButtons()).toHaveLength(0)
      expect(screen.getByLabelText(/^team$/i)).toHaveValue('Whatever FC')
    })

    /**
     * Reviewer finding F9. `loadTeams` only ever calls `setTeamCatalog` in
     * its resolved and rejected paths, so a *refetch* never re-enters
     * `status: 'loading'` -- the flag keeps evaluating against the
     * previously loaded catalog for the whole in-flight window. That is
     * kept deliberately rather than fixed: re-entering `loading` would blank
     * an already-correct notice on every keystroke-triggered refetch and
     * flash it back, and the copy is honest as-is because `catalogScope` is
     * derived from the catalog the form actually holds, never from the
     * pending selection. This test pins that window, which the renamed
     * first-mount test above does not reach.
     *
     * Driven by a *year* change: a league change clears every team value
     * (issue #137), so it no longer leaves a flag behind to re-scope.
     */
    it('keeps naming the loaded scope, not the requested one, while a refetch is in flight', async () => {
      mockedFetchYears.mockResolvedValue({ years: [2018, 2019] })
      let releaseRefetch: (value: TeamsOut) => void = () => {}
      mockedFetchTeams
        .mockResolvedValueOnce(
          teamsOut([{ name: 'Alabama', mascot: 'Crimson Tide', aliases: [] }]),
        )
        .mockImplementationOnce(
          () =>
            new Promise<TeamsOut>((resolvePromise) => {
              releaseRefetch = resolvePromise
            }),
        )
      render(
        <QuestionForm
          onSubmit={vi.fn()}
          initialQuestionType="team_case"
          initialYear={2018}
          initialTeam="Texas"
        />,
      )

      expect(
        await screen.findByText(staleNotice('Texas', '2018 college football')),
      ).toBeInTheDocument()

      // The 2019 catalog request is now in flight and will not resolve until
      // it is released below.
      fireEvent.change(screen.getByLabelText(/year/i), {
        target: { value: '2019' },
      })
      await waitFor(
        () =>
          expect(mockedFetchTeams).toHaveBeenLastCalledWith(
            'cfb',
            'keener',
            2019,
          ),
        { timeout: YEAR_DEBOUNCE_MS * 5 },
      )

      // Mid-flight: still the scope that actually rejected the value, and
      // never a claim about the season nothing has been checked against yet.
      expect(
        screen.getByText(staleNotice('Texas', '2018 college football')),
      ).toBeInTheDocument()
      expect(
        screen.queryByText(staleNotice('Texas', '2019 college football')),
      ).not.toBeInTheDocument()
      expect(clearButtons()).toHaveLength(1)

      releaseRefetch(
        teamsOut([{ name: 'Alabama', mascot: 'Crimson Tide', aliases: [] }]),
      )

      // Once it lands, the same notice re-scopes to the season that now
      // rejects the value.
      expect(
        await screen.findByText(staleNotice('Texas', '2019 college football')),
      ).toBeInTheDocument()
    })

    it('says nothing when the season has no teams ingested at all', async () => {
      mockedFetchTeams.mockResolvedValue({ teams: [], team_details: [] })
      render(
        <QuestionForm
          onSubmit={vi.fn()}
          initialQuestionType="team_case"
          initialYear={2005}
          initialTeam="Whatever FC"
        />,
      )

      // The `empty` state has its own hint, which says the useful thing --
      // on every team field, hence `findAllByText`.
      expect(
        await screen.findAllByText(/no teams found for/i),
      ).not.toHaveLength(0)
      expect(clearButtons()).toHaveLength(0)
    })

    it('says nothing when the team catalog fetch failed', async () => {
      mockedFetchTeams.mockRejectedValue(new Error('network down'))
      render(
        <QuestionForm
          onSubmit={vi.fn()}
          initialQuestionType="team_case"
          initialYear={2005}
          initialTeam="Whatever FC"
        />,
      )

      expect(
        await screen.findAllByText(/couldn't load the team list/i),
      ).not.toHaveLength(0)
      expect(clearButtons()).toHaveLength(0)
    })

    it('flags an out-of-scope "your team", and forgets it only on an explicit clear', async () => {
      stubYearScopedTeams()
      const user = userEvent.setup()
      window.localStorage.setItem('myTeamIsBetter.userTeam', 'Texas')
      render(<QuestionForm onSubmit={vi.fn()} initialYear={2018} />)

      expect(
        await screen.findByText(staleNotice('Texas', '2018 college football')),
      ).toBeInTheDocument()
      expect(window.localStorage.getItem('myTeamIsBetter.userTeam')).toBe(
        'Texas',
      )

      await user.click(
        screen.getByRole('button', { name: 'Clear your saved team' }),
      )

      expect(screen.getByLabelText(/your team/i)).toHaveValue('')
      // An explicit clear is the one thing that *does* forget the stored
      // preference -- `setStoredUserTeam('')` removes the key outright.
      expect(window.localStorage.getItem('myTeamIsBetter.userTeam')).toBeNull()
    })

    it('does not flag a differently-cased or aliased spelling of a team that is in scope', async () => {
      render(
        <QuestionForm
          onSubmit={vi.fn()}
          initialQuestionType="compare"
          initialTeamA="texas"
          initialTeamB="TEX"
        />,
      )

      await waitForInitialCatalog()
      await waitFor(() =>
        expect(screen.getByLabelText(/team a/i)).toHaveAttribute(
          'role',
          'combobox',
        ),
      )
      expect(clearButtons()).toHaveLength(0)
    })
  })

  /**
   * Issue #101. Both catalog effects set a `cancelled` flag in their cleanup
   * and check it before every `setState`. These tests construct the one input
   * that flag exists for -- an *older* request settling after a *newer* one
   * has already landed, on the same mounted form -- and assert the newer
   * catalog survives. Removing either guard turns them red.
   */
  describe('a slow, superseded catalog response never overwrites a newer one (issue #101)', () => {
    it.each(['resolves', 'rejects'] as const)(
      "keeps the newer year's team list when an earlier year's slower request %s after it",
      async (outcome) => {
        mockedFetchYears.mockResolvedValue({ years: [2017, 2018, 2019] })
        const slow2018: { promise?: Promise<TeamsOut>; settle: () => void } = {
          settle: () => {},
        }
        mockedFetchTeams.mockImplementation(
          (_sport?: Sport, _method?: Method, year?: number) => {
            if (year === 2018) {
              slow2018.promise = new Promise<TeamsOut>(
                (resolvePromise, rejectPromise) => {
                  slow2018.settle = () => {
                    // Texas *is* a 2018 team, so a leaked resolve would
                    // silently drop the 2019 flag; a leaked reject would swap
                    // the team hint for the failure copy.
                    if (outcome === 'resolves') {
                      resolvePromise(teamsOut(CFB_DETAILS))
                    } else {
                      rejectPromise(new Error('network down'))
                    }
                  }
                },
              )
              return slow2018.promise
            }
            return Promise.resolve(
              teamsOut(year === 2019 ? [ALABAMA] : CFB_DETAILS),
            )
          },
        )
        render(
          <QuestionForm
            onSubmit={vi.fn()}
            initialQuestionType="team_case"
            initialYear={2017}
            initialTeam="Texas"
          />,
        )
        await waitFor(() =>
          expect(mockedFetchTeams).toHaveBeenCalledWith('cfb', 'keener', 2017),
        )
        const yearInput = screen.getByLabelText(/year/i)

        // Two separate edits, each allowed to settle past the debounce, so
        // both requests genuinely fire -- one debounced edit would issue a
        // single request and leave nothing out of order.
        fireEvent.change(yearInput, { target: { value: '2018' } })
        await waitFor(
          () =>
            expect(mockedFetchTeams).toHaveBeenLastCalledWith(
              'cfb',
              'keener',
              2018,
            ),
          { timeout: YEAR_DEBOUNCE_MS * 5 },
        )
        fireEvent.change(yearInput, { target: { value: '2019' } })
        await waitFor(
          () =>
            expect(mockedFetchTeams).toHaveBeenLastCalledWith(
              'cfb',
              'keener',
              2019,
            ),
          { timeout: YEAR_DEBOUNCE_MS * 5 },
        )
        expect(
          await screen.findByText(
            staleNotice('Texas', '2019 college football'),
          ),
        ).toBeInTheDocument()
        // The precondition the guard exists for -- 2018 still outstanding
        // after 2019 has landed -- is established by the call record above
        // (2018 requested, then 2019) and the 2019 notice. This probe only
        // checks the fixture's half of it: the promise handed out for 2018
        // really is still pending, so an early-settling fixture fails here.
        const pending2018 = slow2018.promise
        if (pending2018 === undefined) {
          throw new Error('the 2018 team-list request never went out')
        }
        expect(await hasSettled(pending2018)).toBe(false)

        slow2018.settle()
        expect(await hasSettled(pending2018)).toBe(true)

        await expectThroughout(() => {
          expect(
            screen.getByText(staleNotice('Texas', '2019 college football')),
          ).toBeInTheDocument()
          expect(
            screen.queryByText(staleNotice('Texas', '2018 college football')),
          ).not.toBeInTheDocument()
          expect(screen.queryByText(TEAM_LIST_FAILED)).not.toBeInTheDocument()
        })
      },
    )

    /**
     * `/api/years` for College held open until `settle`, which resolves or
     * rejects it per `outcome`; NFL answers at once. Both outcomes matter:
     * the effect guards its success path and its failure path separately,
     * and a leaked `{status: 'error', sport: 'cfb'}` replaces the NFL catalog
     * just as surely as a leaked College year list does.
     */
    function stubSlowCollegeYears(outcome: 'resolves' | 'rejects'): {
      promise?: Promise<{ years: number[] }>
      settle: () => void
    } {
      const slow: {
        promise?: Promise<{ years: number[] }>
        settle: () => void
      } = { settle: () => {} }
      mockedFetchYears.mockImplementation((sport?: Sport) => {
        if (sport === 'nfl') {
          return Promise.resolve({ years: [2021, NEWEST_NFL_YEAR] })
        }
        slow.promise = new Promise((resolvePromise, rejectPromise) => {
          slow.settle = () => {
            if (outcome === 'resolves') {
              resolvePromise({ years: [2004, 2005, 2006] })
            } else {
              rejectPromise(new Error('network down'))
            }
          }
        })
        return slow.promise
      })
      mockedFetchTeams.mockImplementation((sport?: Sport) =>
        Promise.resolve(teamsOut(sport === 'nfl' ? NFL_DETAILS : CFB_DETAILS)),
      )
      return slow
    }

    /** Settles the held College request, checking it really was pending. */
    async function settleCollegeYears(slow: {
      promise?: Promise<{ years: number[] }>
      settle: () => void
    }) {
      const pending = slow.promise
      if (pending === undefined) {
        throw new Error('the College years request never went out')
      }
      expect(await hasSettled(pending)).toBe(false)
      slow.settle()
      expect(await hasSettled(pending)).toBe(true)
    }

    it.each(['resolves', 'rejects'] as const)(
      "keeps the NFL's default year when the College years request %s after a switch to the NFL",
      async (outcome) => {
        const slow = stubSlowCollegeYears(outcome)
        const user = userEvent.setup()
        render(<QuestionForm onSubmit={vi.fn()} />)
        await waitFor(() =>
          expect(mockedFetchYears).toHaveBeenCalledWith('cfb', 'keener'),
        )

        await user.click(screen.getByRole('radio', { name: 'NFL' }))
        await waitFor(() =>
          expect(screen.getByLabelText(/year/i)).toHaveValue(NEWEST_NFL_YEAR),
        )
        expect(
          screen.getByText(/seasons with data: 2021-2022/i),
        ).toBeInTheDocument()

        await settleCollegeYears(slow)

        // A leaked College catalog -- years or error -- would replace the NFL
        // one; the render-time league check would then treat the year catalog
        // as still loading, so the default, the hint and the enabled button
        // would all vanish.
        await expectThroughout(() => {
          expect(screen.getByLabelText(/year/i)).toHaveValue(NEWEST_NFL_YEAR)
          expect(
            screen.getByText(/seasons with data: 2021-2022/i),
          ).toBeInTheDocument()
          expect(submitButton()).not.toBeDisabled()
        })
      },
    )

    it.each(['resolves', 'rejects'] as const)(
      'keeps rejecting a year the NFL has no data for when the College years request %s after the switch',
      async (outcome) => {
        const slow = stubSlowCollegeYears(outcome)
        const user = userEvent.setup()
        render(<QuestionForm onSubmit={vi.fn()} />)
        await waitFor(() =>
          expect(mockedFetchYears).toHaveBeenCalledWith('cfb', 'keener'),
        )

        // 2005 is a College season, not an NFL one in this catalog.
        fireEvent.change(screen.getByLabelText(/year/i), {
          target: { value: '2005' },
        })
        await user.click(screen.getByRole('radio', { name: 'NFL' }))
        expect(
          await screen.findByText(
            /no NFL data for 2005/i,
            {},
            { timeout: YEAR_DEBOUNCE_MS * 5 },
          ),
        ).toBeInTheDocument()

        await settleCollegeYears(slow)

        // A leaked College catalog would leave no NFL seasons to check
        // against, and a year with no NFL data would quietly become
        // submittable.
        await expectThroughout(() => {
          expect(screen.getByText(/no NFL data for 2005/i)).toBeInTheDocument()
          expect(screen.getByLabelText(/year/i)).toHaveAttribute(
            'aria-invalid',
            'true',
          )
          expect(submitButton()).toBeDisabled()
        })
      },
    )
  })

  /**
   * Issue #101. A Year that is not a whole number is not a season, in every
   * year-catalog state -- including the three (`loading`, `error`, `ready`
   * but empty) in which `validateYear` has no seasons to check membership
   * against. And it never reaches `/api/teams`, whose `int` `year` would
   * answer 422 and swap every team hint for "Couldn't load the team list".
   */
  describe('non-integer and implausible years (issue #101)', () => {
    const CATALOG_STATES = [
      {
        state: 'ready, with seasons',
        stubYears: () =>
          mockedFetchYears.mockResolvedValue({ years: [2017, 2018, 2019] }),
      },
      {
        state: 'still loading',
        stubYears: () =>
          mockedFetchYears.mockReturnValue(new Promise(() => {})),
      },
      {
        state: 'failed',
        stubYears: () =>
          mockedFetchYears.mockRejectedValue(new Error('network down')),
      },
      {
        state: 'ready, but empty',
        stubYears: () => mockedFetchYears.mockResolvedValue({ years: [] }),
      },
    ]

    it.each(CATALOG_STATES)(
      'rejects "2018.5" while the years catalog is $state, and never sends it to /api/teams',
      async ({ stubYears }) => {
        stubYears()
        stubTeamsRejectingNonIntegerYears()
        render(<QuestionForm onSubmit={vi.fn()} initialYear={2018} />)
        await waitForInitialCatalog()
        await flushSettledRequests()
        const yearInput = screen.getByLabelText(/year/i)

        fireEvent.change(yearInput, { target: { value: '2018.5' } })

        expect(submitButton()).toBeDisabled()
        expect(
          await screen.findByText(
            NOT_A_YEAR_MESSAGE,
            {},
            { timeout: YEAR_DEBOUNCE_MS * 5 },
          ),
        ).toBeInTheDocument()
        // The debounced team refetch fires alongside the message; let it land.
        await flushSettledRequests()

        expect(yearInput).toHaveAttribute('aria-invalid', 'true')
        expect(submitButton()).toBeDisabled()
        expect(nonIntegerTeamFetchYears()).toEqual([])
        expect(screen.queryByText(TEAM_LIST_FAILED)).not.toBeInTheDocument()
      },
    )

    // With no catalog to consult, only the plausibility bound can reject
    // these -- so they are asserted in the failed-catalog state.
    it.each(['999', '10000', '1e21'])(
      'rejects the implausible year "%s" even with no years catalog, and never sends it to /api/teams',
      async (typed) => {
        mockedFetchYears.mockRejectedValue(new Error('network down'))
        render(<QuestionForm onSubmit={vi.fn()} initialYear={2018} />)
        expect(
          await screen.findByText(/couldn't load the list of available years/i),
        ).toBeInTheDocument()
        const yearInput = screen.getByLabelText(/year/i)

        fireEvent.change(yearInput, { target: { value: typed } })

        expect(submitButton()).toBeDisabled()
        expect(
          await screen.findByText(
            NOT_A_YEAR_MESSAGE,
            {},
            { timeout: YEAR_DEBOUNCE_MS * 5 },
          ),
        ).toBeInTheDocument()
        await flushSettledRequests()
        expect(mockedFetchTeams).toHaveBeenLastCalledWith(
          'cfb',
          'keener',
          undefined,
        )
        expect(
          mockedFetchTeams.mock.calls.map(([, , year]) => year),
        ).not.toContain(Number(typed))
      },
    )
  })

  describe('league radios (issue #143)', () => {
    /**
     * The accessible name each league's radio must carry. A `Record<Sport,
     * string>`, so tsc refuses this file until a league added to `SPORTS` is
     * given a name here too -- and the names are pinned, because tests,
     * stories and e2e all query the radios by them.
     */
    const RADIO_NAME: Record<Sport, string> = {
      cfb: 'College',
      nfl: 'NFL',
    }

    it('renders exactly one radio per SPORTS entry, in SPORTS order, each with its value and name', () => {
      render(<QuestionForm onSubmit={vi.fn()} />)

      const group = screen.getByRole('group', { name: 'League' })
      const radios = within(group).getAllByRole('radio')

      expect(radios.map((radio) => radio.getAttribute('value'))).toEqual([
        ...SPORTS,
      ])
      SPORTS.forEach((sport, index) => {
        expect(
          within(group).getByRole('radio', { name: RADIO_NAME[sport] }),
        ).toBe(radios[index])
      })
    })

    it('selects a league through its radio', async () => {
      const user = userEvent.setup()
      render(<QuestionForm onSubmit={vi.fn()} />)
      const group = screen.getByRole('group', { name: 'League' })

      for (const sport of [...SPORTS].reverse()) {
        await user.click(
          within(group).getByRole('radio', { name: RADIO_NAME[sport] }),
        )
        expect(
          within(group).getByRole('radio', { checked: true }),
        ).toHaveAttribute('value', sport)
        await waitFor(() =>
          expect(mockedFetchYears).toHaveBeenLastCalledWith(sport, 'keener'),
        )
      }
    })
  })

  describe('guiding text (issue #52)', () => {
    it('shows the real ingested year range, sourced from /api/years', async () => {
      mockedFetchYears.mockResolvedValue({ years: [2001, 2005, 2013] })
      render(<QuestionForm onSubmit={vi.fn()} />)

      const hint = await screen.findByText(/seasons with data/i)
      expect(hint).toHaveTextContent('2001')
      expect(hint).toHaveTextContent('2013')
    })

    it('gives every one of the four team inputs guiding text', async () => {
      const user = userEvent.setup()
      render(<QuestionForm onSubmit={vi.fn()} />)
      await waitForInitialCatalog()

      // champion: "your team" is the only team input.
      expect(screen.getByLabelText(/your team/i)).toHaveAttribute(
        'placeholder',
        expect.stringMatching(/e\.g\./i),
      )

      await user.selectOptions(
        screen.getByLabelText(/what do you want to know/i),
        'team_case',
      )
      expect(screen.getByLabelText(/^team$/i)).toHaveAttribute(
        'placeholder',
        expect.stringMatching(/e\.g\./i),
      )

      await user.selectOptions(
        screen.getByLabelText(/what do you want to know/i),
        'compare',
      )
      expect(screen.getByLabelText(/team a/i)).toHaveAttribute(
        'placeholder',
        expect.stringMatching(/e\.g\./i),
      )
      expect(screen.getByLabelText(/team b/i)).toHaveAttribute(
        'placeholder',
        expect.stringMatching(/e\.g\./i),
      )
      // ...and hint copy telling the user what is matchable, on each field.
      expect(
        screen.getAllByText(/type a school, mascot, or abbreviation/i),
      ).toHaveLength(3)
    })

    it('keeps the "stays on this device" privacy note on the user-team field', async () => {
      render(<QuestionForm onSubmit={vi.fn()} />)
      await waitForInitialCatalog()

      expect(
        await screen.findByText(/stays on this device only/i),
      ).toBeInTheDocument()
    })

    it('offers league-appropriate team examples', async () => {
      stubSportScopedTeams()
      const user = userEvent.setup()
      render(<QuestionForm onSubmit={vi.fn()} />)
      await waitForInitialCatalog()

      expect(screen.getByLabelText(/your team/i)).toHaveAttribute(
        'placeholder',
        expect.stringMatching(/ohio state/i),
      )

      await user.click(screen.getByRole('radio', { name: /nfl/i }))

      await waitFor(() =>
        expect(screen.getByLabelText(/your team/i)).toHaveAttribute(
          'placeholder',
          expect.stringMatching(/chiefs/i),
        ),
      )
    })

    it('no longer documents the inputs as plain datalist-backed inputs', () => {
      // Read off disk rather than asserting on rendered output: the claim
      // being guarded is in the file's doc comment, which nothing renders.
      // (Vite rewrites `import.meta.url` to a non-`file:` value under test,
      // so this resolves from Vitest's cwd -- `apps/web` -- instead.)
      const source = readFileSync(
        resolve(process.cwd(), 'src/components/QuestionForm/QuestionForm.tsx'),
        'utf8',
      )

      expect(source).not.toMatch(/remain plain, freely-typed/)
      expect(source).not.toMatch(/no data source exists yet/)
      expect(source).toMatch(/TeamCombobox/)
    })
  })

  describe('parent-supplied initial values (issue #38)', () => {
    it('seeds the visible fields from the initial-value props', async () => {
      render(
        <QuestionForm
          onSubmit={vi.fn()}
          initialQuestionType="compare"
          initialSport="nfl"
          initialYear={2018}
          initialTeamA="New York Giants"
          initialTeamB="New York Jets"
        />,
      )

      expect(screen.getByLabelText(/year/i)).toHaveValue(2018)
      expect(screen.getByRole('radio', { name: /nfl/i })).toBeChecked()
      expect(screen.getByLabelText(/team a/i)).toHaveValue('New York Giants')
      expect(screen.getByLabelText(/team b/i)).toHaveValue('New York Jets')
      await waitFor(() =>
        expect(mockedFetchTeams).toHaveBeenCalledWith('nfl', 'keener', 2018),
      )
    })

    it('falls back to College, champion and the newest catalog season when the initial-value props are omitted', async () => {
      render(<QuestionForm onSubmit={vi.fn()} />)

      expect(screen.getByRole('radio', { name: /college/i })).toBeChecked()
      expect(screen.getByLabelText(/what do you want to know/i)).toHaveValue(
        'champion',
      )
      await waitFor(() =>
        expect(screen.getByLabelText(/year/i)).toHaveValue(NEWEST_DEFAULT_YEAR),
      )
    })

    it('seeds the single team field for a team_case correction', () => {
      render(
        <QuestionForm
          onSubmit={vi.fn()}
          initialQuestionType="team_case"
          initialTeam="Texas State"
        />,
      )

      expect(screen.getByLabelText(/^team$/i)).toHaveValue('Texas State')
    })

    /**
     * Issue #184: a share link's `for` team seeds "your team" for this visit
     * only. Opening a friend's link must never overwrite your own saved team.
     */
    describe('initialUserTeam (issue #184)', () => {
      it('seeds "your team" from initialUserTeam instead of the stored value, without writing localStorage', () => {
        window.localStorage.setItem('myTeamIsBetter.userTeam', 'Ohio State')

        render(<QuestionForm onSubmit={vi.fn()} initialUserTeam="Texas" />)

        expect(screen.getByLabelText(/your team/i)).toHaveValue('Texas')
        expect(window.localStorage.getItem('myTeamIsBetter.userTeam')).toBe(
          'Ohio State',
        )
      })

      it('leaves an unset stored team unset', () => {
        render(<QuestionForm onSubmit={vi.fn()} initialUserTeam="Texas" />)

        expect(screen.getByLabelText(/your team/i)).toHaveValue('Texas')
        expect(
          window.localStorage.getItem('myTeamIsBetter.userTeam'),
        ).toBeNull()
      })

      it('seeds an empty field from null, still without touching the stored value', () => {
        window.localStorage.setItem('myTeamIsBetter.userTeam', 'Ohio State')

        render(<QuestionForm onSubmit={vi.fn()} initialUserTeam={null} />)

        expect(screen.getByLabelText(/your team/i)).toHaveValue('')
        expect(window.localStorage.getItem('myTeamIsBetter.userTeam')).toBe(
          'Ohio State',
        )
      })

      it('still reads the stored value when initialUserTeam is omitted', () => {
        window.localStorage.setItem('myTeamIsBetter.userTeam', 'Ohio State')

        render(<QuestionForm onSubmit={vi.fn()} />)

        expect(screen.getByLabelText(/your team/i)).toHaveValue('Ohio State')
      })

      it('submits the seeded team, and writes storage only once the user edits the field', async () => {
        const user = userEvent.setup()
        const onSubmit = vi.fn()
        render(<QuestionForm onSubmit={onSubmit} initialUserTeam="Texas" />)
        const submit = screen.getByRole('button', { name: /get the verdict/i })
        await waitFor(() => expect(submit).not.toBeDisabled())

        await user.click(submit)
        expect(onSubmit).toHaveBeenLastCalledWith(
          expect.objectContaining({ userTeam: 'Texas' }),
        )
        expect(
          window.localStorage.getItem('myTeamIsBetter.userTeam'),
        ).toBeNull()

        // Queried once: focusing the field opens a suggestions listbox whose
        // own label also contains "your team".
        const yourTeam = screen.getByLabelText(/your team/i)
        await user.clear(yourTeam)
        await user.type(yourTeam, 'USC')
        expect(window.localStorage.getItem('myTeamIsBetter.userTeam')).toBe(
          'USC',
        )
      })
    })
  })

  /**
   * Issue #154 (epic #147): the Engine toggle. It scopes both catalogs and the
   * submission to a rating method, and -- unlike a league switch (#137) --
   * keeps the Year and every team value, because a method change is the same
   * season and the same games.
   */
  describe('Engine toggle (issue #154)', () => {
    /**
     * The engines the toggle offers, in order, and each radio's accessible
     * name. Pinned here rather than imported: tests, stories and e2e all query
     * the radios by these names, and `elo_career` is deliberately absent.
     */
    const OFFERED = ['keener', 'elo'] as const
    const ENGINE_RADIO_NAME: Record<(typeof OFFERED)[number], string> = {
      keener: 'Keener (default)',
      elo: 'Elo (second opinion)',
    }

    function engineGroup() {
      return screen.getByRole('group', { name: 'Engine' })
    }

    async function chooseEngine(
      user: ReturnType<typeof userEvent.setup>,
      method: (typeof OFFERED)[number],
    ) {
      await user.click(
        within(engineGroup()).getByRole('radio', {
          name: ENGINE_RADIO_NAME[method],
        }),
      )
    }

    /** Serves a different `/api/years` catalog per engine. */
    function stubEngineYears(keenerYears: number[], eloYears: number[]) {
      mockedFetchYears.mockImplementation((_sport?: Sport, method?: Method) =>
        Promise.resolve({ years: method === 'elo' ? eloYears : keenerYears }),
      )
    }

    it('offers exactly the displayed engines, in order, with Keener checked by default and no elo_career', () => {
      render(<QuestionForm onSubmit={vi.fn()} />)

      const radios = within(engineGroup()).getAllByRole('radio')
      expect(radios.map((radio) => radio.getAttribute('value'))).toEqual([
        ...OFFERED,
      ])
      OFFERED.forEach((method, index) => {
        expect(
          within(engineGroup()).getByRole('radio', {
            name: ENGINE_RADIO_NAME[method],
          }),
        ).toBe(radios[index])
      })
      expect(
        within(engineGroup()).getByRole('radio', { checked: true }),
      ).toHaveAttribute('value', 'keener')
      expect(document.querySelector('input[value="elo_career"]')).toBeNull()
      expect(screen.queryByText(/career/i)).not.toBeInTheDocument()
    })

    it('sits right after the League group', () => {
      render(<QuestionForm onSubmit={vi.fn()} />)

      expect(
        screen.getByRole('group', { name: 'League' }).nextElementSibling,
      ).toBe(engineGroup())
    })

    it('seeds the engine from initialMethod and scopes the first catalog requests to it', async () => {
      render(
        <QuestionForm
          onSubmit={vi.fn()}
          initialMethod="elo"
          initialYear={2005}
        />,
      )

      expect(
        within(engineGroup()).getByRole('radio', {
          name: 'Elo (second opinion)',
        }),
      ).toBeChecked()
      await waitFor(() =>
        expect(mockedFetchTeams).toHaveBeenCalledWith('cfb', 'elo', 2005),
      )
      expect(mockedFetchYears).toHaveBeenCalledWith('cfb', 'elo')
      expect(
        mockedFetchYears.mock.calls.map(([, method]) => method),
      ).not.toContain('keener')
    })

    it('scopes both catalog requests to the selected engine', async () => {
      const user = userEvent.setup()
      render(<QuestionForm onSubmit={vi.fn()} initialYear={2005} />)
      await waitFor(() =>
        expect(mockedFetchTeams).toHaveBeenCalledWith('cfb', 'keener', 2005),
      )
      expect(mockedFetchYears).toHaveBeenCalledWith('cfb', 'keener')

      await chooseEngine(user, 'elo')

      await waitFor(() =>
        expect(mockedFetchYears).toHaveBeenLastCalledWith('cfb', 'elo'),
      )
      await waitFor(() =>
        expect(mockedFetchTeams).toHaveBeenLastCalledWith('cfb', 'elo', 2005),
      )
    })

    it.each([
      {
        questionType: 'champion' as const,
        props: {},
        expected: { questionType: 'champion', year: 2005, userTeam: null },
      },
      {
        questionType: 'team_case' as const,
        props: { initialTeam: 'Texas' },
        expected: {
          questionType: 'team_case',
          year: 2005,
          team: 'Texas',
          userTeam: null,
        },
      },
      {
        questionType: 'compare' as const,
        props: { initialTeamA: 'Texas', initialTeamB: 'USC' },
        expected: {
          questionType: 'compare',
          year: 2005,
          teamA: 'Texas',
          teamB: 'USC',
          userTeam: null,
        },
      },
    ])(
      'sends method "elo" in the $questionType submission once Elo is selected',
      async ({ questionType, props, expected }) => {
        const user = userEvent.setup()
        const onSubmit = vi.fn()
        render(
          <QuestionForm
            onSubmit={onSubmit}
            initialQuestionType={questionType}
            initialYear={2005}
            {...props}
          />,
        )
        await waitForInitialCatalog()

        await chooseEngine(user, 'elo')
        await waitFor(() =>
          expect(mockedFetchYears).toHaveBeenLastCalledWith('cfb', 'elo'),
        )
        await user.click(submitButton())

        expect(onSubmit).toHaveBeenCalledTimes(1)
        expect(onSubmit).toHaveBeenCalledWith({
          ...expected,
          sport: 'cfb',
          method: 'elo',
        })
      },
    )

    it('keeps a typed Year and every compare team value, "your team" and its stored value included, across an engine switch', async () => {
      window.localStorage.setItem('myTeamIsBetter.userTeam', 'Texas')
      const user = userEvent.setup()
      render(
        <QuestionForm
          onSubmit={vi.fn()}
          initialQuestionType="compare"
          initialTeamA="Texas"
          initialTeamB="USC"
        />,
      )
      await waitForDefaultYear()
      fireEvent.change(screen.getByLabelText(/year/i), {
        target: { value: '2005' },
      })

      await chooseEngine(user, 'elo')

      await waitFor(() =>
        expect(mockedFetchTeams).toHaveBeenLastCalledWith('cfb', 'elo', 2005),
      )
      expect(screen.getByLabelText(/year/i)).toHaveValue(2005)
      expect(screen.getByLabelText(/team a/i)).toHaveValue('Texas')
      expect(screen.getByLabelText(/team b/i)).toHaveValue('USC')
      expect(screen.getByLabelText(/your team/i)).toHaveValue('Texas')
      expect(window.localStorage.getItem('myTeamIsBetter.userTeam')).toBe(
        'Texas',
      )
    })

    it('keeps the single team value of a team-case question across an engine switch, and back', async () => {
      const user = userEvent.setup()
      render(
        <QuestionForm
          onSubmit={vi.fn()}
          initialQuestionType="team_case"
          initialYear={2005}
          initialTeam="Texas"
        />,
      )
      await waitForInitialCatalog()

      await chooseEngine(user, 'elo')
      expect(screen.getByLabelText(/^team$/i)).toHaveValue('Texas')
      await chooseEngine(user, 'keener')
      expect(screen.getByLabelText(/^team$/i)).toHaveValue('Texas')
      expect(screen.getByLabelText(/year/i)).toHaveValue(2005)
    })

    it("flags -- but keeps -- a team the new engine's catalog lacks", async () => {
      mockedFetchTeams.mockImplementation((_sport?: Sport, method?: Method) =>
        Promise.resolve(teamsOut(method === 'elo' ? [ALABAMA] : CFB_DETAILS)),
      )
      const user = userEvent.setup()
      render(
        <QuestionForm
          onSubmit={vi.fn()}
          initialQuestionType="team_case"
          initialYear={2005}
          initialTeam="Texas"
        />,
      )
      await waitForInitialCatalog()
      expect(screen.queryByText(ANY_STALE_NOTICE)).not.toBeInTheDocument()

      await chooseEngine(user, 'elo')

      expect(
        await screen.findByText(staleNotice('Texas', '2005 college football')),
      ).toBeInTheDocument()
      expect(screen.getByLabelText(/^team$/i)).toHaveValue('Texas')
    })

    it("moves an untouched default Year to the new engine's newest season", async () => {
      stubEngineYears([2004, 2005, 2006], [2004, 2005, 2006, 2007])
      const user = userEvent.setup()
      render(<QuestionForm onSubmit={vi.fn()} />)
      await waitFor(() =>
        expect(screen.getByLabelText(/year/i)).toHaveValue(NEWEST_DEFAULT_YEAR),
      )

      await chooseEngine(user, 'elo')

      await waitFor(() =>
        expect(screen.getByLabelText(/year/i)).toHaveValue(2007),
      )
    })

    it('never overwrites a seeded Year when the new engine has newer seasons', async () => {
      stubEngineYears([2004, 2005, 2006], [2004, 2005, 2006, 2007])
      const user = userEvent.setup()
      render(<QuestionForm onSubmit={vi.fn()} initialYear={2005} />)
      expect(
        await screen.findByText(/seasons with data: 2004-2006/i),
      ).toBeInTheDocument()

      await chooseEngine(user, 'elo')

      expect(
        await screen.findByText(/seasons with data: 2004-2007/i),
      ).toBeInTheDocument()
      expect(screen.getByLabelText(/year/i)).toHaveValue(2005)
    })

    it("never validates against, or hints at, the previous engine's seasons while the new engine's are in flight", async () => {
      let releaseElo: (years: number[]) => void = () => {}
      mockedFetchYears.mockImplementation((_sport?: Sport, method?: Method) =>
        method === 'elo'
          ? new Promise((resolvePromise) => {
              releaseElo = (years) => resolvePromise({ years })
            })
          : Promise.resolve({ years: [2004, 2005, 2006] }),
      )
      const user = userEvent.setup()
      render(<QuestionForm onSubmit={vi.fn()} initialYear={2007} />)
      expect(
        await screen.findByText(
          /no college football data for 2007/i,
          {},
          { timeout: YEAR_DEBOUNCE_MS * 5 },
        ),
      ).toBeInTheDocument()
      expect(submitButton()).toBeDisabled()

      await chooseEngine(user, 'elo')
      await waitFor(() =>
        expect(mockedFetchYears).toHaveBeenLastCalledWith('cfb', 'elo'),
      )

      // Keener's seasons say nothing about Elo's: nothing to check against yet.
      expect(
        screen.queryByText(/seasons with data: 2004-2006/i),
      ).not.toBeInTheDocument()
      expect(
        screen.queryByText(/no college football data for 2007/i),
      ).not.toBeInTheDocument()
      expect(submitButton()).not.toBeDisabled()

      await act(async () => {
        releaseElo([2005, 2006, 2007])
      })

      expect(
        await screen.findByText(/seasons with data: 2005-2007/i),
      ).toBeInTheDocument()
      expect(screen.getByLabelText(/year/i)).toHaveValue(2007)
      expect(submitButton()).not.toBeDisabled()
    })

    describe('a slow, superseded catalog response for the previous engine never overwrites the new one', () => {
      it.each(['resolves', 'rejects'] as const)(
        "keeps Elo's default Year when Keener's slower years request %s after the switch",
        async (outcome) => {
          const slow: {
            promise?: Promise<{ years: number[] }>
            settle: () => void
          } = { settle: () => {} }
          mockedFetchYears.mockImplementation(
            (_sport?: Sport, method?: Method) => {
              if (method === 'elo') {
                return Promise.resolve({ years: [2005, 2006, 2007] })
              }
              slow.promise = new Promise((resolvePromise, rejectPromise) => {
                slow.settle = () => {
                  if (outcome === 'resolves') {
                    resolvePromise({ years: [2004, 2005, 2006] })
                  } else {
                    rejectPromise(new Error('network down'))
                  }
                }
              })
              return slow.promise
            },
          )
          const user = userEvent.setup()
          render(<QuestionForm onSubmit={vi.fn()} />)
          await waitFor(() =>
            expect(mockedFetchYears).toHaveBeenCalledWith('cfb', 'keener'),
          )

          await chooseEngine(user, 'elo')
          await waitFor(() =>
            expect(screen.getByLabelText(/year/i)).toHaveValue(2007),
          )
          expect(
            screen.getByText(/seasons with data: 2005-2007/i),
          ).toBeInTheDocument()

          const pending = slow.promise
          if (pending === undefined) {
            throw new Error('the Keener years request never went out')
          }
          expect(await hasSettled(pending)).toBe(false)
          slow.settle()
          expect(await hasSettled(pending)).toBe(true)

          await expectThroughout(() => {
            expect(screen.getByLabelText(/year/i)).toHaveValue(2007)
            expect(
              screen.getByText(/seasons with data: 2005-2007/i),
            ).toBeInTheDocument()
            expect(submitButton()).not.toBeDisabled()
          })
        },
      )

      it.each(['resolves', 'rejects'] as const)(
        "keeps Elo's team list when Keener's slower team-list request %s after the switch",
        async (outcome) => {
          const slow: { promise?: Promise<TeamsOut>; settle: () => void } = {
            settle: () => {},
          }
          mockedFetchTeams.mockImplementation(
            (_sport?: Sport, method?: Method) => {
              if (method === 'elo') {
                return Promise.resolve(teamsOut([ALABAMA]))
              }
              slow.promise = new Promise<TeamsOut>(
                (resolvePromise, rejectPromise) => {
                  slow.settle = () => {
                    // Texas *is* in Keener's list, so a leaked resolve would
                    // silently drop Elo's flag; a leaked reject would swap the
                    // team hint for the failure copy.
                    if (outcome === 'resolves') {
                      resolvePromise(teamsOut(CFB_DETAILS))
                    } else {
                      rejectPromise(new Error('network down'))
                    }
                  }
                },
              )
              return slow.promise
            },
          )
          const user = userEvent.setup()
          render(
            <QuestionForm
              onSubmit={vi.fn()}
              initialQuestionType="team_case"
              initialYear={2005}
              initialTeam="Texas"
            />,
          )
          await waitFor(() =>
            expect(mockedFetchTeams).toHaveBeenCalledWith(
              'cfb',
              'keener',
              2005,
            ),
          )

          await chooseEngine(user, 'elo')
          await waitFor(() =>
            expect(mockedFetchTeams).toHaveBeenLastCalledWith(
              'cfb',
              'elo',
              2005,
            ),
          )
          expect(
            await screen.findByText(
              staleNotice('Texas', '2005 college football'),
            ),
          ).toBeInTheDocument()

          const pending = slow.promise
          if (pending === undefined) {
            throw new Error('the Keener team-list request never went out')
          }
          expect(await hasSettled(pending)).toBe(false)
          slow.settle()
          expect(await hasSettled(pending)).toBe(true)

          await expectThroughout(() => {
            expect(
              screen.getByText(staleNotice('Texas', '2005 college football')),
            ).toBeInTheDocument()
            expect(screen.queryByText(TEAM_LIST_FAILED)).not.toBeInTheDocument()
          })
        },
      )
    })
  })
})
