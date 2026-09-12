import type { Sport, VerdictErrorState } from '../../lib/api/types'
import styles from './VerdictError.module.css'

/**
 * How a league is named in user-facing copy. Deliberately not the wire value
 * (`cfb`/`nfl`): "no rating for 2010 cfb" is jargon, and the whole point of
 * the `unknown_team` copy is to say which season *and* which league came up
 * empty.
 */
const LEAGUE_LABEL: Record<Sport, string> = {
  cfb: 'college football',
  nfl: 'NFL',
}

export interface VerdictErrorProps {
  state: VerdictErrorState
  /** Re-submits the same question with a different, known-good year (unknown_year only). */
  onSelectYear?: (year: number) => void
  /**
   * Re-submits the same question with the exact team name picked from a pill
   * -- `ambiguous_team`'s candidates, and only those. `unknown_team` offers
   * no pills at all (see that branch below), so this is unused there.
   */
  onSelectCandidate?: (candidate: string) => void
}

/**
 * Renders one of the four HTTP error cases from `apps/api/src/api/errors.py`
 * (404 unknown_year, 404 unknown_team, 422 ambiguous_team, 400
 * same_team_comparison) or a generic network/unreachable-API failure, each
 * distinctly.
 */
export function VerdictError({
  state,
  onSelectYear,
  onSelectCandidate,
}: VerdictErrorProps) {
  switch (state.kind) {
    case 'unknown_year':
      return (
        <div role="alert" className={styles.pick}>
          <p className={styles.msg}>
            No ratings are available for {state.body.year}. Try one of the years
            that do have data:
          </p>
          <ul className={styles.chipList}>
            {state.body.available_years.map((year) => (
              <li key={year}>
                <button
                  type="button"
                  className={`${styles.chip} ${styles.chipYear}`}
                  onClick={() => onSelectYear?.(year)}
                >
                  {year}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )
    case 'ambiguous_team':
      return (
        <div role="alert" className={styles.pick}>
          <p className={styles.msg}>
            &ldquo;{state.body.query}&rdquo; could mean more than one team. Did
            you mean:
          </p>
          <ul className={styles.chipList}>
            {state.body.candidates.map((candidate) => (
              <li key={candidate}>
                <button
                  type="button"
                  className={`${styles.chip} ${styles.chipTeam}`}
                  onClick={() => onSelectCandidate?.(candidate)}
                >
                  {candidate}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )
    case 'unknown_team': {
      // Split out of `ambiguous_team` in issue #100, and deliberately a
      // *single* render with no correction pills. An earlier cut offered
      // fuzzy-matched suggestions; they were dropped from the contract
      // because nothing that reaches this branch scores high enough to be a
      // real correction (the engine resolves >= 0.6 upstream), so the pills
      // could only ever show real-but-irrelevant teams. Saying plainly that
      // nothing was found, and naming the scope that came up empty, is the
      // honest answer -- and it is still not a dead end, because it says
      // what to change.
      const { query, year, sport } = state.body
      const scope = `${year} ${LEAGUE_LABEL[sport]}`
      return (
        <div role="alert" className={`${styles.plain} ${styles.user}`}>
          <p>
            We don&apos;t have a {scope} rating for &ldquo;{query}&rdquo;. Try a
            different season, or switch leagues.
          </p>
        </div>
      )
    }
    case 'same_team_comparison':
      return (
        <div role="alert" className={`${styles.plain} ${styles.user}`}>
          <p>
            {state.body.team_name} can&apos;t be compared to itself. Pick two
            different teams.
          </p>
        </div>
      )
    case 'network_error':
      return (
        <div role="alert" className={`${styles.plain} ${styles.system}`}>
          <p>{state.message}</p>
        </div>
      )
  }
}
