import { useId, useState } from 'react'
import type { FormEvent } from 'react'
import { getStoredUserTeam, setStoredUserTeam } from '../../lib/userTeam'

export type QuestionType = 'champion' | 'team_case' | 'compare'

export interface ChampionSubmission {
  questionType: 'champion'
  year: number
  userTeam: string | null
}

export interface TeamCaseSubmission {
  questionType: 'team_case'
  year: number
  team: string
  userTeam: string | null
}

export interface CompareSubmission {
  questionType: 'compare'
  year: number
  teamA: string
  teamB: string
  userTeam: string | null
}

export type QuestionSubmission =
  ChampionSubmission | TeamCaseSubmission | CompareSubmission

export interface QuestionFormProps {
  /** Called with a validated, question-type-specific submission shape. */
  onSubmit: (submission: QuestionSubmission) => void
  /** True while a previous submission's request is still in flight. */
  isSubmitting?: boolean
}

const CURRENT_YEAR = new Date().getFullYear()

/**
 * Structured question form (PRD §5.1: pickers/selects, not a chat box) for
 * the three verdict question types. No team/year picker data source exists
 * yet (issue #13) -- year is a plain number input and team names are plain
 * text inputs; the API's error responses (see `VerdictError`) are the
 * correction mechanism for a mistyped team or an un-ingested year.
 */
export function QuestionForm({
  onSubmit,
  isSubmitting = false,
}: QuestionFormProps) {
  const questionTypeId = useId()
  const yearId = useId()
  const teamId = useId()
  const teamAId = useId()
  const teamBId = useId()
  const userTeamId = useId()

  const [questionType, setQuestionType] = useState<QuestionType>('champion')
  const [year, setYear] = useState(String(CURRENT_YEAR))
  const [team, setTeam] = useState('')
  const [teamA, setTeamA] = useState('')
  const [teamB, setTeamB] = useState('')
  const [userTeam, setUserTeam] = useState(() => getStoredUserTeam())

  function handleUserTeamChange(value: string) {
    setUserTeam(value)
    setStoredUserTeam(value)
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const parsedYear = Number(year)
    if (!Number.isFinite(parsedYear)) {
      return
    }
    const trimmedUserTeam = userTeam.trim()
    const submissionUserTeam = trimmedUserTeam === '' ? null : trimmedUserTeam

    if (questionType === 'champion') {
      onSubmit({
        questionType: 'champion',
        year: parsedYear,
        userTeam: submissionUserTeam,
      })
      return
    }
    if (questionType === 'team_case') {
      onSubmit({
        questionType: 'team_case',
        year: parsedYear,
        team: team.trim(),
        userTeam: submissionUserTeam,
      })
      return
    }
    onSubmit({
      questionType: 'compare',
      year: parsedYear,
      teamA: teamA.trim(),
      teamB: teamB.trim(),
      userTeam: submissionUserTeam,
    })
  }

  return (
    <form onSubmit={handleSubmit}>
      <div>
        <label htmlFor={questionTypeId}>What do you want to know?</label>
        <select
          id={questionTypeId}
          value={questionType}
          onChange={(event) =>
            setQuestionType(event.target.value as QuestionType)
          }
        >
          <option value="champion">Who was the best team in a year?</option>
          <option value="team_case">How good was a team in a year?</option>
          <option value="compare">Was one team better than another?</option>
        </select>
      </div>

      <div>
        <label htmlFor={yearId}>Year</label>
        <input
          id={yearId}
          type="number"
          value={year}
          onChange={(event) => setYear(event.target.value)}
          required
        />
      </div>

      {questionType === 'team_case' && (
        <div>
          <label htmlFor={teamId}>Team</label>
          <input
            id={teamId}
            type="text"
            value={team}
            onChange={(event) => setTeam(event.target.value)}
            required
          />
        </div>
      )}

      {questionType === 'compare' && (
        <>
          <div>
            <label htmlFor={teamAId}>Team A</label>
            <input
              id={teamAId}
              type="text"
              value={teamA}
              onChange={(event) => setTeamA(event.target.value)}
              required
            />
          </div>
          <div>
            <label htmlFor={teamBId}>Team B</label>
            <input
              id={teamBId}
              type="text"
              value={teamB}
              onChange={(event) => setTeamB(event.target.value)}
              required
            />
          </div>
        </>
      )}

      <div>
        <label htmlFor={userTeamId}>Your team (optional)</label>
        <input
          id={userTeamId}
          type="text"
          value={userTeam}
          onChange={(event) => handleUserTeamChange(event.target.value)}
          placeholder="Stays on this device only"
        />
      </div>

      <button type="submit" disabled={isSubmitting}>
        {isSubmitting ? 'Getting the verdict…' : 'Get the verdict'}
      </button>
    </form>
  )
}
