import { useEffect, useId, useState } from 'react'
import type { FormEvent } from 'react'
import { fetchTeams, fetchYears } from '../../lib/api/client'
import type { Sport, TeamDetail } from '../../lib/api/types'
import { getStoredUserTeam, setStoredUserTeam } from '../../lib/userTeam'
import { TeamCombobox } from '../TeamCombobox/TeamCombobox'
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
  /**
   * Seed values for the fields this form owns internally (issue #38). Each
   * is an *initial* value only -- read once, on mount, exactly like
   * `userTeam`'s `localStorage` read below; later prop changes are ignored,
   * so typing is never fought by a parent re-render. A parent applying a
   * correction (e.g. `HomePage`'s year/candidate pills) therefore remounts
   * this form with a changed `key` rather than pushing new props into a
   * mounted one. Omitting them all preserves the pre-#38 defaults.
   */
  initialQuestionType?: QuestionType
  initialSport?: Sport
  initialYear?: number
  initialTeam?: string
  initialTeamA?: string
  initialTeamB?: string
}

const CURRENT_YEAR = new Date().getFullYear()

/**
 * How long the Year input sits still before its team-list refetch fires.
 * Year is a free-typed `<input type="number">`, so an undebounced refetch
 * would issue one request per keystroke ("2010" -> four requests, three of
 * them for the meaningless years 2, 20 and 201). Exported so the tests
 * assert against the real value instead of a copied magic number.
 */
export const YEAR_DEBOUNCE_MS = 300

/**
 * `/api/years` results, backing the Year input's `<datalist>` and its
 * "seasons with data" hint. Not year-scoped, so this refetches on a league
 * change only. `error` degrades to a plain typed year, never a block.
 */
interface YearCatalogState {
  status: 'loading' | 'ready' | 'error'
  years: number[]
}

/**
 * `/api/teams` results, backing all four `TeamCombobox` fields.
 *
 * `empty` and `error` are deliberately **separate** states, because they
 * mean different things to the user and must read differently: `empty` is a
 * successful year-scoped response (`{teams: [], team_details: []}`) saying
 * "that season isn't ingested", while `error` means the catalog request
 * itself failed. Both degrade the comboboxes to plain typed inputs; only
 * one of them is worth telling the user to try another year about.
 */
interface TeamCatalogState {
  status: 'loading' | 'ready' | 'empty' | 'error'
  teams: TeamDetail[]
  /** The year whose (empty) result produced this state, for the `empty` copy. */
  year: number | undefined
}

const EMPTY_YEAR_CATALOG: YearCatalogState = { status: 'loading', years: [] }
const EMPTY_TEAM_CATALOG: TeamCatalogState = {
  status: 'loading',
  teams: [],
  year: undefined,
}

const TEAM_FETCH_FAILED_HINT =
  "Couldn't load the team list -- you can still type any name."
const YEAR_FETCH_FAILED_HINT =
  "Couldn't load the list of available years -- you can still enter one."
/** Privacy note testers have already seen -- it survives every other state. */
const USER_TEAM_PRIVACY_HINT = 'Stays on this device only.'

/**
 * Resolves the raw Year input string to a year worth sending to
 * `/api/teams`, or `undefined` to send no `year` param at all (which asks
 * for the full per-sport list -- the right pre-selection state).
 *
 * `Number('')` is `0`, a *finite* number, so an emptied input has to be
 * screened out here rather than relying on `Number.isFinite` alone.
 */
function parseYear(raw: string): number | undefined {
  if (raw.trim() === '') {
    return undefined
  }
  const parsed = Number(raw)
  return Number.isFinite(parsed) ? parsed : undefined
}

/**
 * Returns `value` only once it has stopped changing for `delayMs`. Deliberately
 * hand-rolled (no new runtime dependency) and initialised *to* `value`, so the
 * first render fetches immediately and only subsequent edits pay the delay.
 */
function useDebouncedValue<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value)

  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), delayMs)
    return () => {
      window.clearTimeout(timer)
    }
  }, [value, delayMs])

  return debounced
}

/** `Seasons with data: 2000-2023.` -- the real ingested range (issue #52),
 * derived from `/api/years` so it can never drift from what is actually
 * queryable, and honest about gaps rather than implying a solid span. */
function formatSeasonsHint(years: number[]): string | undefined {
  if (years.length === 0) {
    return undefined
  }
  const min = Math.min(...years)
  const max = Math.max(...years)
  if (min === max) {
    return `Seasons with data: ${min}.`
  }
  const isContiguous = years.length === max - min + 1
  return isContiguous
    ? `Seasons with data: ${min}-${max}.`
    : `Seasons with data: ${min}-${max} (with gaps).`
}

/**
 * Structured question form (PRD §5.1: pickers/selects, not a chat box) for
 * the three verdict question types.
 *
 * All four team fields -- `team`, `teamA`, `teamB` and the optional "your
 * team" -- are `TeamCombobox`es (issue #80), fed from `/api/teams` scoped to
 * **both** the selected league and the entered year, so the typeahead can
 * never offer an NFL team to a College question or a team that has no rating
 * for the year being asked about. That replaces the `<datalist>` the form
 * used to hang off three of the four inputs while leaving "your team" with
 * no typeahead at all. The Year input keeps a `<datalist>`: its suggestions
 * are short, exact numbers with no secondary display text, which is the one
 * case `<datalist>` actually handles well.
 *
 * Suggestions never gate submission, in any of the catalog's states: a
 * failed fetch, a year with nothing ingested, and a still-in-flight request
 * all leave plain typed inputs plus a hint that says which of those it is.
 * `apps/api`'s mapped error responses (see `VerdictError`) remain the
 * correction mechanism for a genuinely mistyped team or an un-ingested
 * year, and `HomePage` feeds an accepted correction back in through this
 * form's `initial*` props so the visible fields agree with what was asked
 * (issue #38).
 */
export function QuestionForm({
  onSubmit,
  isSubmitting = false,
  initialQuestionType,
  initialSport,
  initialYear,
  initialTeam,
  initialTeamA,
  initialTeamB,
}: QuestionFormProps) {
  const questionTypeId = useId()
  const sportName = useId()
  const yearId = useId()
  const yearListId = useId()

  const [questionType, setQuestionType] = useState<QuestionType>(
    initialQuestionType ?? 'champion',
  )
  const [sport, setSport] = useState<Sport>(initialSport ?? 'cfb')
  const [year, setYear] = useState(String(initialYear ?? CURRENT_YEAR))
  const [team, setTeam] = useState(initialTeam ?? '')
  const [teamA, setTeamA] = useState(initialTeamA ?? '')
  const [teamB, setTeamB] = useState(initialTeamB ?? '')
  const [userTeam, setUserTeam] = useState(() => getStoredUserTeam())
  const [yearCatalog, setYearCatalog] =
    useState<YearCatalogState>(EMPTY_YEAR_CATALOG)
  const [teamCatalog, setTeamCatalog] =
    useState<TeamCatalogState>(EMPTY_TEAM_CATALOG)

  // Only the *team* list is year-scoped, and only the year is free-typed, so
  // the debounce sits here and not on the league toggle: switching to NFL
  // still refetches immediately.
  const debouncedYear = useDebouncedValue(year, YEAR_DEBOUNCE_MS)

  useEffect(() => {
    let cancelled = false

    async function loadYears() {
      try {
        const yearsOut = await fetchYears(sport)
        if (!cancelled) {
          setYearCatalog({ status: 'ready', years: yearsOut.years })
        }
      } catch {
        if (!cancelled) {
          setYearCatalog({ status: 'error', years: [] })
        }
      }
    }

    void loadYears()
    return () => {
      cancelled = true
    }
  }, [sport])

  useEffect(() => {
    let cancelled = false
    const scopedYear = parseYear(debouncedYear)

    async function loadTeams() {
      try {
        const teamsOut = await fetchTeams(sport, scopedYear)
        if (cancelled) {
          return
        }
        // Presentation ordering is a presentation concern: the API orders by
        // `teams.id`, which is arbitrary to a user, and `TeamCombobox`
        // breaks ranking ties by arrival order -- so "New York" would offer
        // the Giants and the Jets in an unpredictable order without this.
        const teams = [...teamsOut.team_details].sort((a, b) =>
          a.name.localeCompare(b.name),
        )
        setTeamCatalog({
          status: teams.length === 0 ? 'empty' : 'ready',
          teams,
          year: scopedYear,
        })
      } catch {
        if (!cancelled) {
          setTeamCatalog({ status: 'error', teams: [], year: scopedYear })
        }
      }
    }

    void loadTeams()
    return () => {
      cancelled = true
    }
  }, [sport, debouncedYear])

  function handleUserTeamChange(value: string) {
    setUserTeam(value)
    setStoredUserTeam(value)
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const parsedYear = parseYear(year)
    if (parsedYear === undefined) {
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

  // Guiding text (issue #52): a first-time user should be able to fill every
  // field in without guessing at the format or the ingested range.
  const teamPlaceholder =
    sport === 'nfl' ? 'e.g. Kansas City Chiefs' : 'e.g. Ohio State'
  const teamMatchHint =
    sport === 'nfl'
      ? 'Type a city or team name, then pick from the list.'
      : 'Type a school, mascot, or abbreviation, then pick from the list.'
  const teamHint =
    teamCatalog.status === 'error'
      ? TEAM_FETCH_FAILED_HINT
      : teamCatalog.status === 'empty'
        ? teamCatalog.year === undefined
          ? 'No teams are ingested for this league yet -- you can still type a name.'
          : `No teams found for ${teamCatalog.year} -- try another season, or type a name anyway.`
        : teamMatchHint
  const seasonsHint = formatSeasonsHint(yearCatalog.years)
  const yearHint =
    yearCatalog.status === 'error' ? YEAR_FETCH_FAILED_HINT : seasonsHint

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
          list={yearCatalog.years.length > 0 ? yearListId : undefined}
          value={year}
          onChange={(event) => setYear(event.target.value)}
          placeholder={
            yearCatalog.years.length > 0
              ? String(Math.max(...yearCatalog.years))
              : undefined
          }
          required
        />
        {yearHint !== undefined && (
          <p className={styles.catalogHint}>{yearHint}</p>
        )}
      </div>

      {yearCatalog.years.length > 0 && (
        <datalist id={yearListId}>
          {yearCatalog.years.map((availableYear) => (
            <option key={availableYear} value={availableYear} />
          ))}
        </datalist>
      )}

      {questionType === 'team_case' && (
        <TeamCombobox
          label="Team"
          teams={teamCatalog.teams}
          value={team}
          onChange={setTeam}
          placeholder={teamPlaceholder}
          hint={teamHint}
          required
        />
      )}

      {questionType === 'compare' && (
        <div className={styles.qfieldPair}>
          <TeamCombobox
            label="Team A"
            teams={teamCatalog.teams}
            value={teamA}
            onChange={setTeamA}
            placeholder={teamPlaceholder}
            hint={teamHint}
            required
          />
          <TeamCombobox
            label="Team B"
            teams={teamCatalog.teams}
            value={teamB}
            onChange={setTeamB}
            placeholder={teamPlaceholder}
            hint={teamHint}
            required
          />
        </div>
      )}

      <div className={styles.casual}>
        <TeamCombobox
          label="Your team (optional)"
          teams={teamCatalog.teams}
          value={userTeam}
          onChange={handleUserTeamChange}
          placeholder={teamPlaceholder}
          hint={`${USER_TEAM_PRIVACY_HINT} ${teamHint}`}
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
