import type { VerdictCardState } from '../../lib/api/types'
import { isTeamCaseEnvelope } from '../../lib/api/types'
import { ComparisonReceipts } from '../EvidenceReceipts/ComparisonReceipts'
import { TeamCaseReceipts } from '../EvidenceReceipts/TeamCaseReceipts'
import { VerdictError } from '../VerdictError/VerdictError'

export interface VerdictCardProps {
  state: VerdictCardState
  /** Re-submits the same question with a different, known-good year (unknown_year only). */
  onSelectYear?: (year: number) => void
  /** Re-submits the same question with the exact resolved team name (ambiguous_team only). */
  onSelectCandidate?: (candidate: string) => void
}

/**
 * Renders the persona's narration text plus the evidence "receipts"
 * underneath (PRD §3 / Architecture Brief §4.3's "show your work"), or one
 * of the loading/error states while there's no verdict to show yet.
 */
export function VerdictCard({
  state,
  onSelectYear,
  onSelectCandidate,
}: VerdictCardProps) {
  if (state.status === 'loading') {
    return <p role="status">Getting the verdict…</p>
  }

  if (state.status === 'error') {
    return (
      <VerdictError
        state={state.error}
        onSelectYear={onSelectYear}
        onSelectCandidate={onSelectCandidate}
      />
    )
  }

  const { envelope } = state
  return (
    <article>
      <blockquote>{envelope.narration.text}</blockquote>
      {envelope.narration.contested && (
        <p>This one's contested -- reasonable people disagree.</p>
      )}
      {isTeamCaseEnvelope(envelope) ? (
        <TeamCaseReceipts evidence={envelope.evidence} />
      ) : (
        <ComparisonReceipts evidence={envelope.evidence} />
      )}
    </article>
  )
}
