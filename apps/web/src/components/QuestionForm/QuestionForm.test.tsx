import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Sport, TeamDetail, TeamsOut } from '../../lib/api/types'
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

/** The year the form defaults to -- mirrors `QuestionForm`'s own `CURRENT_YEAR`. */
const CURRENT_YEAR = new Date().getFullYear()

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

/** Serves sport-scoped team details, so a league-scoping assertion has
 * something to actually scope against. */
function stubSportScopedTeams() {
  mockedFetchTeams.mockImplementation((sport?: Sport) =>
    Promise.resolve(teamsOut(sport === 'nfl' ? NFL_DETAILS : CFB_DETAILS)),
  )
  mockedFetchYears.mockImplementation((sport?: Sport) =>
    Promise.resolve({
      years: sport === 'nfl' ? [2021, 2022] : [2004, 2005, 2006],
    }),
  )
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

    await user.clear(screen.getByLabelText(/year/i))
    await user.type(screen.getByLabelText(/year/i), '2005')
    await user.click(screen.getByRole('button', { name: /get the verdict/i }))

    expect(onSubmit).toHaveBeenCalledWith({
      questionType: 'champion',
      year: 2005,
      userTeam: null,
      sport: 'cfb',
    })
  })

  it('submits a team-case question with the right shape', async () => {
    const user = userEvent.setup()
    const onSubmit = vi.fn()
    render(<QuestionForm onSubmit={onSubmit} />)

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
    })
  })

  it('submits a compare question with the right shape, including a persisted user team', async () => {
    const user = userEvent.setup()
    const onSubmit = vi.fn()
    render(<QuestionForm onSubmit={onSubmit} />)

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

    it('does not block initial render while the catalog fetch is still in flight', () => {
      mockedFetchYears.mockReturnValue(new Promise(() => {}))
      mockedFetchTeams.mockReturnValue(new Promise(() => {}))

      render(<QuestionForm onSubmit={vi.fn()} />)

      expect(screen.getByLabelText(/year/i)).toBeInTheDocument()
      expect(
        screen.getByRole('button', { name: /get the verdict/i }),
      ).not.toBeDisabled()
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
        expect(mockedFetchTeams).toHaveBeenLastCalledWith('nfl', CURRENT_YEAR),
      )
      await user.click(screen.getByLabelText(/your team/i))

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
    it('sends the current year with the initial team fetch', async () => {
      render(<QuestionForm onSubmit={vi.fn()} />)

      await waitFor(() =>
        expect(mockedFetchTeams).toHaveBeenCalledWith('cfb', CURRENT_YEAR),
      )
      // /api/years is not year-scoped -- its request shape is untouched.
      expect(mockedFetchYears).toHaveBeenCalledWith('cfb')
    })

    it('refetches the team list when the year changes', async () => {
      render(<QuestionForm onSubmit={vi.fn()} />)
      await waitForInitialCatalog()
      mockedFetchTeams.mockClear()

      fireEvent.change(screen.getByLabelText(/year/i), {
        target: { value: '2005' },
      })

      await waitFor(() =>
        expect(mockedFetchTeams).toHaveBeenCalledWith('cfb', 2005),
      )
    })

    it('debounces the year-driven refetch: typing "2010" issues one request, not four', async () => {
      render(<QuestionForm onSubmit={vi.fn()} />)
      await waitForInitialCatalog()
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
      expect(mockedFetchTeams).toHaveBeenCalledWith('cfb', 2010)
    })

    it('sends no year at all while the year input is empty', async () => {
      render(<QuestionForm onSubmit={vi.fn()} />)
      await waitForInitialCatalog()
      mockedFetchTeams.mockClear()

      fireEvent.change(screen.getByLabelText(/year/i), {
        target: { value: '' },
      })

      await waitFor(() => expect(mockedFetchTeams).toHaveBeenCalledTimes(1))
      // `Number('')` is 0, a finite number -- an emptied input must still
      // ask for the whole per-sport list, not for year 0.
      expect(mockedFetchTeams).toHaveBeenCalledWith('cfb', undefined)
    })

    it('refetches immediately (not debounced) when the league toggles', async () => {
      stubSportScopedTeams()
      const user = userEvent.setup()
      render(<QuestionForm onSubmit={vi.fn()} />)
      await waitForInitialCatalog()

      await user.click(screen.getByRole('radio', { name: /nfl/i }))

      await waitFor(() =>
        expect(mockedFetchTeams).toHaveBeenLastCalledWith('nfl', CURRENT_YEAR),
      )
      expect(mockedFetchYears).toHaveBeenLastCalledWith('nfl')
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
      })
    })

    it('reads an empty year-scoped list differently from a failed fetch', async () => {
      mockedFetchTeams.mockResolvedValue({ teams: [], team_details: [] })
      render(<QuestionForm onSubmit={vi.fn()} />)

      await waitForInitialCatalog()

      const emptyNote = await screen.findByText(
        new RegExp(`no teams .*${CURRENT_YEAR}`, 'i'),
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
      await waitForInitialCatalog()

      await user.clear(screen.getByLabelText(/year/i))
      await user.type(screen.getByLabelText(/year/i), '2005')
      await user.click(screen.getByRole('button', { name: /get the verdict/i }))

      expect(onSubmit).toHaveBeenCalledWith({
        questionType: 'champion',
        year: 2005,
        userTeam: null,
        sport: 'cfb',
      })
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
        expect(mockedFetchTeams).toHaveBeenCalledWith('nfl', 2018),
      )
    })

    it('falls back to today defaults when the initial-value props are omitted', () => {
      render(<QuestionForm onSubmit={vi.fn()} />)

      expect(screen.getByLabelText(/year/i)).toHaveValue(CURRENT_YEAR)
      expect(screen.getByRole('radio', { name: /college/i })).toBeChecked()
      expect(screen.getByLabelText(/what do you want to know/i)).toHaveValue(
        'champion',
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
  })
})
