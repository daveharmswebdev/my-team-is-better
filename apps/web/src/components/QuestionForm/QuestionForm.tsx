import { useEffect, useId, useState } from 'react'
import type { FormEvent } from 'react'
import { fetchTeams, fetchYears } from '../../lib/api/client'
import type { Sport } from '../../lib/api/types'
import { getStoredUserTeam, setStoredUserTeam } from '../../lib/userTeam'
import styles from './QuestionForm.module.css'

export type QuestionType = 'champion' | 'team_case' | 'compare'

export interface ChampionSubmission {
  questionType: 'champion'
  year: number
  userTeam: string | null
  sport: Sport
}

export interface TeamCaseSubmission {
  questionType: 'team_case'
  year: number
  team: string
  userTeam: string | null
  sport: Sport
}

export interface CompareSubmission {
  questionType: 'compare'
  year: number
  teamA: string
  teamB: string
  userTeam: string | null
  sport: Sport
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

/** Fetched `/api/years` / `/api/teams` results, used only to populate the
 * year/team `<datalist>` suggestions below -- see `CatalogState`'s doc
 * comment for how a fetch failure degrades. */
interface CatalogState {
  status: 'loading' | 'ready' | 'error'
  years: number[]
  teams: string[]
}

const EMPTY_CATALOG: CatalogState = { status: 'loading', years: [], teams: [] }

/**
 * Structured question form (PRD §5.1: pickers/selects, not a chat box) for
 * the three verdict question types. Year and team-name inputs are backed by
 * `apps/api`'s `/api/years` / `/api/teams` catalog endpoints (issue #13,
 * closed; wired up here per issue #56) via `<datalist>` suggestions -- they
 * remain plain, freely-typed `<input>` elements (not a combobox/autocomplete
 * redesign), and the catalog fetch failing degrades silently to today's
 * unvalidated-input behavior rather than blocking submission. The API's
 * mapped error responses (see `VerdictError`) remain the correction
 * mechanism for a still-mistyped team or an actually-un-ingested year.
 */
export function QuestionForm({
  onSubmit,
  isSubmitting = false,
}: QuestionFormProps) {
  const questionTypeId = useId()
  const sportName = useId()
  const yearId = useId()
  const teamId = useId()
  const teamAId = useId()
  const teamBId = useId()
  const userTeamId = useId()
  const yearListId = useId()
  const teamListId = useId()

  const [questionType, setQuestionType] = useState<QuestionType>('champion')
  const [sport, setSport] = useState<Sport>('cfb')
  const [year, setYear] = useState(String(CURRENT_YEAR))
  const [team, setTeam] = useState('')
  const [teamA, setTeamA] = useState('')
  const [teamB, setTeamB] = useState('')
  const [userTeam, setUserTeam] = useState(() => getStoredUserTeam())
  const [catalog, setCatalog] = useState<CatalogState>(EMPTY_CATALOG)

  useEffect(() => {
    let cancelled = false

    async function loadCatalog() {
      try {
        const [yearsOut, teamsOut] = await Promise.all([
          fetchYears(sport),
          fetchTeams(sport),
        ])
        if (!cancelled) {
          setCatalog({
            status: 'ready',
            years: yearsOut.years,
            teams: teamsOut.teams,
          })
        }
      } catch {
        if (!cancelled) {
          setCatalog((previous) => ({ ...previous, status: 'error' }))
        }
      }
    }

    void loadCatalog()
    return () => {
      cancelled = true
    }
  }, [sport])

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
        sport,
      })
      return
    }
    if (questionType === 'team_case') {
      onSubmit({
        questionType: 'team_case',
        year: parsedYear,
        team: team.trim(),
        userTeam: submissionUserTeam,
        sport,
      })
      return
    }
    onSubmit({
      questionType: 'compare',
      year: parsedYear,
      teamA: teamA.trim(),
      teamB: teamB.trim(),
      userTeam: submissionUserTeam,
      sport,
    })
  }

  return (
    <form className={styles.qform} onSubmit={handleSubmit}>
      <fieldset className={styles.sportToggle}>
        <legend>League</legend>
        <label>
          <input
            type="radio"
            name={sportName}
            value="cfb"
            checked={sport === 'cfb'}
            onChange={() => setSport('cfb')}
          />
          College
        </label>
        <label>
          <input
            type="radio"
            name={sportName}
            value="nfl"
            checked={sport === 'nfl'}
            onChange={() => setSport('nfl')}
          />
          NFL
        </label>
      </fieldset>

      <div className={styles.qfield}>
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

      <div className={styles.qfield}>
        <label htmlFor={yearId}>Year</label>
        <input
          id={yearId}
          type="number"
          list={catalog.years.length > 0 ? yearListId : undefined}
          value={year}
          onChange={(event) => setYear(event.target.value)}
          required
        />
        {catalog.status === 'error' && (
          <p className={styles.catalogHint}>
            Couldn&apos;t load the list of available years -- you can still
            enter one.
          </p>
        )}
      </div>

      {questionType === 'team_case' && (
        <div className={styles.qfield}>
          <label htmlFor={teamId}>Team</label>
          <input
            id={teamId}
            type="text"
            list={catalog.teams.length > 0 ? teamListId : undefined}
            value={team}
            onChange={(event) => setTeam(event.target.value)}
            required
          />
          {catalog.status === 'error' && (
            <p className={styles.catalogHint}>
              Couldn&apos;t load the team list -- you can still type any name.
            </p>
          )}
        </div>
      )}

      {questionType === 'compare' && (
        <div className={styles.qfieldPair}>
          <div className={styles.qfield}>
            <label htmlFor={teamAId}>Team A</label>
            <input
              id={teamAId}
              type="text"
              list={catalog.teams.length > 0 ? teamListId : undefined}
              value={teamA}
              onChange={(event) => setTeamA(event.target.value)}
              required
            />
          </div>
          <div className={styles.qfield}>
            <label htmlFor={teamBId}>Team B</label>
            <input
              id={teamBId}
              type="text"
              list={catalog.teams.length > 0 ? teamListId : undefined}
              value={teamB}
              onChange={(event) => setTeamB(event.target.value)}
              required
            />
          </div>
          {catalog.status === 'error' && (
            <p className={styles.catalogHint}>
              Couldn&apos;t load the team list -- you can still type any name.
            </p>
          )}
        </div>
      )}

      {catalog.years.length > 0 && (
        <datalist id={yearListId}>
          {catalog.years.map((availableYear) => (
            <option key={availableYear} value={availableYear} />
          ))}
        </datalist>
      )}
      {catalog.teams.length > 0 && (
        <datalist id={teamListId}>
          {catalog.teams.map((name) => (
            <option key={name} value={name} />
          ))}
        </datalist>
      )}

      <div className={`${styles.qfield} ${styles.casual}`}>
        <label htmlFor={userTeamId}>Your team (optional)</label>
        <input
          id={userTeamId}
          type="text"
          value={userTeam}
          onChange={(event) => handleUserTeamChange(event.target.value)}
          placeholder="Stays on this device only"
        />
      </div>

      <button
        className={`${styles.btn} ${styles.btnPrimary}`}
        type="submit"
        disabled={isSubmitting}
      >
        {isSubmitting ? 'Getting the verdict…' : 'Get the verdict'}
      </button>
    </form>
  )
}
