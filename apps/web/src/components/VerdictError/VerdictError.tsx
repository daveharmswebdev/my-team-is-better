import type { VerdictErrorState } from '../../lib/api/types'

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
        <div role="alert">
          <p>
            No ratings are available for {state.body.year}. Try one of the years
            that do have data:
          </p>
          <ul>
            {state.body.available_years.map((year) => (
              <li key={year}>
                <button type="button" onClick={() => onSelectYear?.(year)}>
                  {year}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )
    case 'ambiguous_team':
      return (
        <div role="alert">
          <p>
            &ldquo;{state.body.query}&rdquo; could mean more than one team. Did
            you mean:
          </p>
          <ul>
            {state.body.candidates.map((candidate) => (
              <li key={candidate}>
                <button
                  type="button"
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
        <div role="alert">
          <p>
            {state.body.team_name} can&apos;t be compared to itself. Pick two
            different teams.
          </p>
        </div>
      )
    case 'network_error':
      return (
        <div role="alert">
          <p>{state.message}</p>
        </div>
      )
  }
}
