import { useEffect, useId, useState } from 'react'
import type { FormEvent } from 'react'
import { fetchTeams, fetchYears } from '../../lib/api/client'
import { SPORTS } from '../../lib/api/types'
import type { Method, Sport, TeamDetail } from '../../lib/api/types'
import {
  DISPLAYED_METHODS,
  ENGINE_LEGEND,
  METHOD_RADIO_LABEL,
} from '../../lib/methods'
import { getStoredUserTeam, setStoredUserTeam } from '../../lib/userTeam'
import { TeamCombobox } from '../TeamCombobox/TeamCombobox'
import { isTeamInCatalog } from '../TeamCombobox/teamMatching'
import styles from './QuestionForm.module.css'

export type QuestionType = 'champion' | 'team_case' | 'compare'

export interface ChampionSubmission {
  questionType: 'champion'
  year: number
  userTeam: string | null
  sport: Sport
  /** The Engine toggle's rating method at submit time (issue #154). */
  method: Method
}

export interface TeamCaseSubmission {
  questionType: 'team_case'
  year: number
  team: string
  userTeam: string | null
  sport: Sport
  /** The Engine toggle's rating method at submit time (issue #154). */
  method: Method
}

export interface CompareSubmission {
  questionType: 'compare'
  year: number
  teamA: string
  teamB: string
  userTeam: string | null
  sport: Sport
  /** The Engine toggle's rating method at submit time (issue #154). */
  method: Method
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
   * mounted one. Omitting them all preserves the defaults: College, Keener,
   * the champion question, and the newest season with data (issue #136).
   */
  initialQuestionType?: QuestionType
  initialSport?: Sport
  /** The Engine toggle's initial method (issue #154) -- same read-once semantics. */
  initialMethod?: Method
  initialYear?: number
  initialTeam?: string
  initialTeamA?: string
  initialTeamB?: string
  /**
   * The "Your team (optional)" field's initial value (issue #184) -- same
   * read-once semantics. When given (`null` seeds an empty field) it is used
   * *instead of* the stored team and is **not** written to `localStorage`:
   * a share link's `for` team belongs to that visit, so opening a friend's
   * link never overwrites your own saved team. Only a real edit to the field
   * writes storage, as always. Omitted (`undefined`), the field reads the
   * stored team exactly as before.
   */
  initialUserTeam?: string | null
}

/**
 * How long the Year input sits still before its team-list refetch fires --
 * and before an invalid year's inline error appears. Year is a free-typed
 * `<input type="number">`, so an undebounced refetch would issue one request
 * per keystroke ("2010" -> four requests, three of them for the meaningless
 * years 2, 20 and 201), and an undebounced error would flash "no data for 2"
 * on the way to a perfectly good year. Exported so the tests assert against
 * the real value instead of a copied magic number.
 */
export const YEAR_DEBOUNCE_MS = 300

/**
 * `/api/years` results, backing the Year input's default, its validation,
 * its `<datalist>` and its "seasons with data" hint. Not year-scoped, so
 * this refetches on a league or engine change only. `error` degrades to a
 * plain typed year, never a block.
 */
interface YearCatalogState {
  status: 'loading' | 'ready' | 'error'
  years: number[]
  /**
   * The league and engine these years describe, both `null` before any
   * response. A catalog for any other league *or* engine than the selected
   * pair is treated as still `loading`, so a league or engine switch can
   * never validate against -- or default to -- the previous scope's seasons
   * while the new ones are in flight (issue #154: an engine only has seasons
   * it actually rated).
   */
  sport: Sport | null
  method: Method | null
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
  /**
   * The scope this catalog actually describes -- *not* the form's current
   * selection, which can already have moved on while a refetch is in
   * flight. The `empty` hint and the stale-value flag (issue #100) both name
   * this scope to the user, so naming the requested-but-not-yet-loaded one
   * would flash copy that was never true. `year` is `undefined` when the
   * Year input was empty and the full per-sport list was requested.
   */
  year: number | undefined
  sport: Sport
}

const EMPTY_YEAR_CATALOG: YearCatalogState = {
  status: 'loading',
  years: [],
  sport: null,
  method: null,
}
// `year`/`sport` are only ever read in the `ready`/`empty` states, so the
// pre-first-response placeholder does not describe any real scope.
const EMPTY_TEAM_CATALOG: TeamCatalogState = {
  status: 'loading',
  teams: [],
  year: undefined,
  sport: 'cfb',
}

/** User-facing league names -- `cfb`/`nfl` are wire values, not copy. */
const LEAGUE_LABEL: Record<Sport, string> = {
  cfb: 'college football',
  nfl: 'NFL',
}

/**
 * Each league radio's visible text, which is also its accessible name.
 * Separate from `LEAGUE_LABEL` because a toggle reads differently from
 * running copy ("College", not "college football"). The radios are rendered
 * from `SPORTS` (issue #143), so tsc requires a label here for every league
 * and none can be added to `SPORTS` without becoming selectable.
 */
const LEAGUE_RADIO_LABEL: Record<Sport, string> = {
  cfb: 'College',
  nfl: 'NFL',
}

const TEAM_FETCH_FAILED_HINT =
  "Couldn't load the team list -- you can still type any name."
const YEAR_FETCH_FAILED_HINT =
  "Couldn't load the list of available years -- you can still enter one."
/** Privacy note testers have already seen -- it survives every other state. */
const USER_TEAM_PRIVACY_HINT = 'Stays on this device only.'

/**
 * The widest range of values `parseYear` accepts as a year at all: four
 * digits. This is a *shape* check, deliberately not a data check. Which
 * seasons have data is `/api/years`' job (`validateYear`) with `apps/api`'s
 * `unknown_year` as the backstop, and a football-history bound (say 1869, the
 * first college game) would duplicate that job with a number that goes stale.
 * It would also contradict issue #136's rule that a failed or empty catalog
 * never blocks a typed year. What the bound does rule out is input that can
 * never be a season, which `<input type="number">` happily accepts: `999`,
 * `-2018`, `10000`, and exponent forms outside the range, like `1e21`, which
 * `String()` renders as `"1e+21"`, a value the API's `int` `year` answers
 * with a 422. An exponent form *inside* the range is not ruled out: `1e3` is
 * `Number` 1000 and goes to the API as the plain `1000`, which is harmless.
 */
const MIN_PLAUSIBLE_YEAR = 1000
const MAX_PLAUSIBLE_YEAR = 9999

/**
 * Resolves the raw Year input string to a year worth sending to
 * `/api/teams`, or `undefined` to send no `year` param at all (which asks
 * for the full per-sport list -- the right pre-selection state).
 *
 * `Number('')` is `0`, a *finite* number, so an emptied input has to be
 * screened out here rather than relying on `Number.isFinite` alone. And a
 * season is a whole number: `2018.5` is finite but no season, and the API's
 * `int` `year` would answer it with a 422 (issue #101) -- so it resolves to
 * `undefined` too, which `validateYear` reports in every catalog state.
 */
function parseYear(raw: string): number | undefined {
  if (raw.trim() === '') {
    return undefined
  }
  const parsed = Number(raw)
  return Number.isInteger(parsed) &&
    parsed >= MIN_PLAUSIBLE_YEAR &&
    parsed <= MAX_PLAUSIBLE_YEAR
    ? parsed
    : undefined
}

/**
 * The Year field's verdict (issue #136). `message` is the inline error copy,
 * and is `undefined` for an empty field -- the disabled submit button is
 * explanation enough for a blank, and an error on an untouched-looking
 * field reads as the form scolding the user for not having started yet.
 */
type YearValidity = { valid: true } | { valid: false; message?: string }

/**
 * Checks `raw` against the selected league's year catalog.
 *
 * Only a `ready` catalog with at least one season range-checks, and it
 * checks *membership*, not min/max: `formatSeasonsHint` already admits
 * catalogs can have gaps, and a year inside a gap has no data either. Every
 * other state has nothing to check against, so any year `parseYear` accepts
 * (a whole, four-digit number -- issue #101) goes: a catalog
 * still `loading`, one that `error`ed, and a `ready` but empty one -- a
 * league with nothing ingested yet, which the team hint likewise answers
 * with "you can still type a name". Neither a failed `/api/years` nor an
 * empty league may hard-block the form; `apps/api`'s `unknown_year`
 * response remains the backstop for those cases.
 */
function validateYear(
  raw: string,
  catalog: YearCatalogState,
  sport: Sport,
): YearValidity {
  if (raw.trim() === '') {
    return { valid: false }
  }
  const parsed = parseYear(raw)
  if (parsed === undefined) {
    return { valid: false, message: 'Enter the season as a year, e.g. 2025.' }
  }
  if (
    catalog.status !== 'ready' ||
    catalog.years.length === 0 ||
    catalog.years.includes(parsed)
  ) {
    return { valid: true }
  }
  return {
    valid: false,
    message: `No ${LEAGUE_LABEL[sport]} data for ${parsed} -- ${seasonsToPickFrom(catalog.years)}`,
  }
}

/**
 * The "what to pick instead" half of the invalid-year message. Only ever
 * called with a non-empty catalog -- `validateYear` accepts any year against
 * an empty one.
 */
function seasonsToPickFrom(years: number[]): string {
  const min = Math.min(...years)
  const max = Math.max(...years)
  if (min === max) {
    return `the only season with data is ${min}.`
  }
  return years.length === max - min + 1
    ? `pick a season from ${min}-${max}.`
    : `pick a season from ${min}-${max} (with gaps: not every season in that range has data).`
}

/**
 * Returns `value` only once it has stopped changing for `delayMs`. Deliberately
 * hand-rolled (no new runtime dependency) and initialised *to* `value`, so the
 * first render sees it immediately and only subsequent edits pay the delay.
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

/**
 * The inline flag for a team value the loaded catalog does not contain
 * (issue #100). It names the value, the season and the league that stopped
 * recognising it, because "we don't know this one" is only actionable with
 * the scope attached -- and it offers a clear, rather than performing one.
 *
 * `role="status"` (polite), not `alert`: nothing is broken and nothing is
 * blocked. The visible button text stays "Clear" so it is contained in
 * `clearLabel`, the field-qualified accessible name -- WCAG 2.5.3 requires
 * that containment, and the qualifier is what keeps two of these
 * distinguishable on a compare question. `clearLabel` deliberately
 * paraphrases the field ("the first team", not "Team A"): an `aria-label`
 * is a label as far as `getByLabelText` is concerned, so echoing the
 * field's own label here would make every existing query for that field
 * ambiguous.
 */
function StaleTeamNotice({
  clearLabel,
  value,
  scope,
  onClear,
}: {
  clearLabel: string
  value: string
  scope: string
  onClear: () => void
}) {
  return (
    <div className={styles.staleTeam}>
      <p role="status" className={styles.staleTeamText}>
        &ldquo;{value}&rdquo; isn&apos;t in the {scope} team list -- you can
        still ask about it.
      </p>
      <button
        type="button"
        className={styles.staleTeamClear}
        aria-label={clearLabel}
        onClick={onClear}
      >
        Clear
      </button>
    </div>
  )
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
 * Team suggestions never gate submission, in any of the catalog's states: a
 * failed fetch, a year with nothing ingested, and a still-in-flight request
 * all leave plain typed inputs plus a hint that says which of those it is.
 * `apps/api`'s mapped error responses (see `VerdictError`) remain the
 * correction mechanism for a genuinely mistyped team, and `HomePage` feeds
 * an accepted correction back in through this form's `initial*` props so the
 * visible fields agree with what was asked (issue #38).
 *
 * The Year is the one field that does gate submission (issue #136). It
 * defaults to the newest season `/api/years` reports for the selected league
 * -- never the calendar year, which is routinely a season nothing has been
 * ingested for -- and an untouched default follows a league switch to the
 * new league's newest season, while a typed or parent-seeded year is never
 * overwritten. See `validateYear` for what counts as valid in each of the
 * year catalog's states; a failed or empty catalog never blocks a whole
 * four-digit year (`parseYear`'s shape check still applies in every state).
 *
 * The **Engine** toggle (issue #154) picks the rating method both catalogs
 * and the submission are scoped to. It offers `DISPLAYED_METHODS` only, and
 * it affects the *next* submission only -- a verdict already on screen keeps
 * the engine that answered it. Changing the engine keeps the Year and every
 * team value: unlike a league switch it is the same season and the same
 * games, so a team the new engine's catalog lacks is flagged like a year
 * change's, never cleared. An untouched default Year follows the new
 * engine's newest season exactly as it follows a league switch.
 *
 * Changing the **league** clears all four team values, "your team" and its
 * stored preference included (issue #137): a team name means nothing in the
 * other league, so a College pick carried into an NFL question is only
 * something to notice and delete by hand. Changing the **year** deliberately
 * does *not* clear or revalidate them (issue #100): a team is usually still
 * a team a season over, so a value the new season's catalog lacks is
 * *flagged* -- named, scoped and one click from being cleared -- and stays
 * submittable. Silently discarding typed input is its own annoyance, and a
 * freely-typed name has to stay submittable for the same reason the degraded
 * catalog states above do.
 */
export function QuestionForm({
  onSubmit,
  isSubmitting = false,
  initialQuestionType,
  initialSport,
  initialMethod,
  initialYear,
  initialTeam,
  initialTeamA,
  initialTeamB,
  initialUserTeam,
}: QuestionFormProps) {
  const questionTypeId = useId()
  const sportName = useId()
  const methodName = useId()
  const yearId = useId()
  const yearListId = useId()
  const yearErrorId = useId()

  const [questionType, setQuestionType] = useState<QuestionType>(
    initialQuestionType ?? 'champion',
  )
  const [sport, setSport] = useState<Sport>(initialSport ?? 'cfb')
  const [method, setMethod] = useState<Method>(initialMethod ?? 'keener')
  /**
   * The Year the user (or the parent, via `initialYear`) actually chose, or
   * `null` while the field is still showing the catalog-derived default.
   * Keeping "untouched" as `null` rather than a copied-in number is what lets
   * the default follow the catalog without ever overwriting a real choice --
   * and an emptied field is a choice too (`''`), not a request to refill it.
   */
  const [typedYear, setTypedYear] = useState<string | null>(
    initialYear === undefined ? null : String(initialYear),
  )
  const [team, setTeam] = useState(initialTeam ?? '')
  const [teamA, setTeamA] = useState(initialTeamA ?? '')
  const [teamB, setTeamB] = useState(initialTeamB ?? '')
  // A parent-seeded team (issue #184) replaces the stored one for this mount
  // and is deliberately not written back: see `initialUserTeam`.
  const [userTeam, setUserTeam] = useState(() =>
    initialUserTeam === undefined
      ? getStoredUserTeam()
      : (initialUserTeam ?? ''),
  )
  const [loadedYearCatalog, setYearCatalog] =
    useState<YearCatalogState>(EMPTY_YEAR_CATALOG)
  const [teamCatalog, setTeamCatalog] =
    useState<TeamCatalogState>(EMPTY_TEAM_CATALOG)

  // See `YearCatalogState.sport`/`.method`: another league's or another
  // engine's years are no years at all.
  const yearCatalog =
    loadedYearCatalog.sport === sport && loadedYearCatalog.method === method
      ? loadedYearCatalog
      : EMPTY_YEAR_CATALOG
  const newestYear =
    yearCatalog.status === 'ready' && yearCatalog.years.length > 0
      ? Math.max(...yearCatalog.years)
      : undefined
  const defaultYear = newestYear === undefined ? '' : String(newestYear)
  const year = typedYear ?? defaultYear
  const yearValidity = validateYear(year, yearCatalog, sport)

  // Only the *team* list is year-scoped, and only the year is free-typed, so
  // the debounce sits on the typed value and not on the league or engine
  // toggles or the catalog-derived default: switching to NFL or to Elo, or
  // the default arriving, refetches immediately. Until a fresh edit has
  // settled, the team fetch keeps the year the field showed before typing
  // began.
  const debouncedTypedYear = useDebouncedValue(typedYear, YEAR_DEBOUNCE_MS)
  const teamScopeYear =
    typedYear === null || debouncedTypedYear === null
      ? defaultYear
      : debouncedTypedYear
  const yearHasSettled = typedYear === null || debouncedTypedYear === typedYear
  const yearError =
    !yearValidity.valid && yearHasSettled ? yearValidity.message : undefined

  useEffect(() => {
    let cancelled = false

    async function loadYears() {
      try {
        const yearsOut = await fetchYears(sport, method)
        if (!cancelled) {
          setYearCatalog({
            status: 'ready',
            years: yearsOut.years,
            sport,
            method,
          })
        }
      } catch {
        if (!cancelled) {
          setYearCatalog({ status: 'error', years: [], sport, method })
        }
      }
    }

    void loadYears()
    return () => {
      cancelled = true
    }
  }, [sport, method])

  useEffect(() => {
    let cancelled = false
    const scopedYear = parseYear(teamScopeYear)

    async function loadTeams() {
      try {
        const teamsOut = await fetchTeams(sport, method, scopedYear)
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
          sport,
        })
      } catch {
        if (!cancelled) {
          setTeamCatalog({
            status: 'error',
            teams: [],
            year: scopedYear,
            sport,
          })
        }
      }
    }

    void loadTeams()
    return () => {
      cancelled = true
    }
    // `method` in the deps is what makes `cancelled` cover an engine switch
    // too: the previous engine's in-flight response is discarded.
  }, [sport, method, teamScopeYear])

  function handleUserTeamChange(value: string) {
    setUserTeam(value)
    setStoredUserTeam(value)
  }

  /** Issue #137: a real league change empties every team field. Re-selecting
   * the current league is not a change and leaves them alone. */
  function handleSportChange(next: Sport) {
    if (next === sport) {
      return
    }
    setSport(next)
    setTeam('')
    setTeamA('')
    setTeamB('')
    handleUserTeamChange('')
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const parsedYear = parseYear(year)
    // Backstop for the disabled button: Enter in a field, or a programmatic
    // submit, must not slip an invalid year past it.
    if (parsedYear === undefined || !yearValidity.valid) {
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
        method,
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
        method,
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
      method,
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
  /**
   * Whether to flag `value` as out of scope. Only `ready` qualifies: while
   * `loading` there is nothing to check against, and `empty`/`error` already
   * say the useful thing in their own hint -- "not in the catalog" means
   * nothing when there is no catalog. Blank values are never flagged, and
   * the check is never a submission gate.
   */
  function isOutOfScope(value: string): boolean {
    return (
      teamCatalog.status === 'ready' &&
      value.trim() !== '' &&
      !isTeamInCatalog(teamCatalog.teams, value)
    )
  }

  // Named off the catalog's own scope, not the current selection -- see
  // `TeamCatalogState`.
  const catalogScope =
    teamCatalog.year === undefined
      ? LEAGUE_LABEL[teamCatalog.sport]
      : `${teamCatalog.year} ${LEAGUE_LABEL[teamCatalog.sport]}`

  const seasonsHint = formatSeasonsHint(yearCatalog.years)
  const yearHint =
    yearCatalog.status === 'error' ? YEAR_FETCH_FAILED_HINT : seasonsHint

  return (
    <form className={styles.qform} onSubmit={handleSubmit}>
      <fieldset className={styles.sportToggle}>
        <legend>League</legend>
        {SPORTS.map((league) => (
          <label key={league}>
            <input
              type="radio"
              name={sportName}
              value={league}
              checked={sport === league}
              onChange={() => handleSportChange(league)}
            />
            {LEAGUE_RADIO_LABEL[league]}
          </label>
        ))}
      </fieldset>

      {/* Issue #154: the toggle affects the next submission only, and never
          clears Year or team values -- see the component doc. */}
      <fieldset className={styles.engineToggle}>
        <legend>{ENGINE_LEGEND}</legend>
        {DISPLAYED_METHODS.map((engine) => (
          <label key={engine}>
            <input
              type="radio"
              name={methodName}
              value={engine}
              checked={method === engine}
              onChange={() => setMethod(engine)}
            />
            {METHOD_RADIO_LABEL[engine]}
          </label>
        ))}
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
          onChange={(event) => setTypedYear(event.target.value)}
          placeholder={
            newestYear === undefined ? undefined : String(newestYear)
          }
          aria-invalid={yearError === undefined ? undefined : true}
          aria-describedby={yearError === undefined ? undefined : yearErrorId}
          required
        />
        {yearError !== undefined && (
          <p id={yearErrorId} className={styles.fieldError}>
            {yearError}
          </p>
        )}
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
        <div>
          <TeamCombobox
            label="Team"
            teams={teamCatalog.teams}
            value={team}
            onChange={setTeam}
            placeholder={teamPlaceholder}
            hint={teamHint}
            required
          />
          {isOutOfScope(team) && (
            <StaleTeamNotice
              clearLabel="Clear the team"
              value={team.trim()}
              scope={catalogScope}
              onClear={() => setTeam('')}
            />
          )}
        </div>
      )}

      {questionType === 'compare' && (
        <div className={styles.qfieldPair}>
          <div>
            <TeamCombobox
              label="Team A"
              teams={teamCatalog.teams}
              value={teamA}
              onChange={setTeamA}
              placeholder={teamPlaceholder}
              hint={teamHint}
              required
            />
            {isOutOfScope(teamA) && (
              <StaleTeamNotice
                clearLabel="Clear the first team"
                value={teamA.trim()}
                scope={catalogScope}
                onClear={() => setTeamA('')}
              />
            )}
          </div>
          <div>
            <TeamCombobox
              label="Team B"
              teams={teamCatalog.teams}
              value={teamB}
              onChange={setTeamB}
              placeholder={teamPlaceholder}
              hint={teamHint}
              required
            />
            {isOutOfScope(teamB) && (
              <StaleTeamNotice
                clearLabel="Clear the second team"
                value={teamB.trim()}
                scope={catalogScope}
                onClear={() => setTeamB('')}
              />
            )}
          </div>
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
        {isOutOfScope(userTeam) && (
          <StaleTeamNotice
            clearLabel="Clear your saved team"
            value={userTeam.trim()}
            scope={catalogScope}
            onClear={() => handleUserTeamChange('')}
          />
        )}
      </div>

      <button
        className={`${styles.btn} ${styles.btnPrimary}`}
        type="submit"
        // The live year, not the debounced one: the button must never be
        // clickable on a year the error has simply not caught up with yet.
        disabled={isSubmitting || !yearValidity.valid}
      >
        {isSubmitting ? 'Getting the verdict…' : 'Get the verdict'}
      </button>
    </form>
  )
}
