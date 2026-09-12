import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { QuestionForm } from './QuestionForm'

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

describe('QuestionForm', () => {
  beforeEach(() => {
    window.localStorage.clear()
    mockedFetchYears.mockReset()
    mockedFetchTeams.mockReset()
    mockedFetchYears.mockResolvedValue({ years: [2004, 2005, 2006] })
    mockedFetchTeams.mockResolvedValue({ teams: ['Texas', 'USC'] })
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

  describe('catalog-backed year/team suggestions', () => {
    it('fetches the catalog on mount and offers fetched years as datalist suggestions', async () => {
      render(<QuestionForm onSubmit={vi.fn()} />)

      await waitFor(() => expect(mockedFetchYears).toHaveBeenCalled())
      const yearInput = screen.getByLabelText(/year/i)
      const yearListId = yearInput.getAttribute('list')
      expect(yearListId).toBeTruthy()
      const yearList = document.getElementById(yearListId ?? '')
      expect(yearList).not.toBeNull()
      const yearOptions = within(yearList as HTMLElement).getAllByRole(
        'option',
        { hidden: true },
      )
      expect(yearOptions.map((option) => option.getAttribute('value'))).toEqual(
        ['2004', '2005', '2006'],
      )
    })

    it('offers fetched team names as datalist suggestions on the team field', async () => {
      const user = userEvent.setup()
      render(<QuestionForm onSubmit={vi.fn()} />)

      await user.selectOptions(
        screen.getByLabelText(/what do you want to know/i),
        'team_case',
      )

      const teamInput = await screen.findByLabelText(/^team$/i)
      await waitFor(() => expect(mockedFetchTeams).toHaveBeenCalled())
      await waitFor(() => expect(teamInput.getAttribute('list')).toBeTruthy())
      const teamListId = teamInput.getAttribute('list')
      const teamList = document.getElementById(teamListId ?? '')
      expect(teamList).not.toBeNull()
      const teamOptions = within(teamList as HTMLElement).getAllByRole(
        'option',
        { hidden: true },
      )
      expect(teamOptions.map((option) => option.getAttribute('value'))).toEqual(
        ['Texas', 'USC'],
      )
    })

    it('offers the same fetched team names on both compare fields', async () => {
      const user = userEvent.setup()
      render(<QuestionForm onSubmit={vi.fn()} />)

      await user.selectOptions(
        screen.getByLabelText(/what do you want to know/i),
        'compare',
      )
      await waitFor(() => expect(mockedFetchTeams).toHaveBeenCalled())

      const teamAInput = screen.getByLabelText(/team a/i)
      const teamBInput = screen.getByLabelText(/team b/i)
      await waitFor(() => expect(teamAInput.getAttribute('list')).toBeTruthy())
      expect(teamAInput.getAttribute('list')).toBe(
        teamBInput.getAttribute('list'),
      )
    })

    it('still lets the form be submitted with unvalidated input if the catalog fetch fails', async () => {
      mockedFetchYears.mockRejectedValue(new Error('network down'))
      mockedFetchTeams.mockRejectedValue(new Error('network down'))
      const user = userEvent.setup()
      const onSubmit = vi.fn()
      render(<QuestionForm onSubmit={onSubmit} />)

      await waitFor(() => expect(mockedFetchYears).toHaveBeenCalled())

      const yearInput = screen.getByLabelText(/year/i)
      expect(yearInput.getAttribute('list')).toBeFalsy()

      await user.clear(yearInput)
      await user.type(yearInput, '2005')
      await user.click(screen.getByRole('button', { name: /get the verdict/i }))

      expect(onSubmit).toHaveBeenCalledWith({
        questionType: 'champion',
        year: 2005,
        userTeam: null,
      })
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
})
