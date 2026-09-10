import type { VerdictErrorState } from '../../lib/api/types'
import styles from './VerdictError.module.css'

export interface VerdictErrorProps {
  state: VerdictErrorState
  /** Re-submits the same question with a different, known-good year (unknown_year only). */
  onSelectYear?: (year: number) => void
  /** Re-submits the same question with the exact resolved team name (ambiguous_team only). */
  onSelectCandidate?: (candidate: string) => void
}

/**
 * Renders one of the three HTTP error cases from `apps/api/src/api/errors.py`
 * (404 unknown_year, 422 ambiguous_team, 400 same_team_comparison) or a
 * generic network/unreachable-API failure, each distinctly.
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
