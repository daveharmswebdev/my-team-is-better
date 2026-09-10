import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { QuestionForm } from './QuestionForm'

describe('QuestionForm', () => {
  beforeEach(() => {
    window.localStorage.clear()
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
})
