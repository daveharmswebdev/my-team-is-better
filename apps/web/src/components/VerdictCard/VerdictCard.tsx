import type { VerdictCardState } from '../../lib/api/types'
import { isTeamCaseEnvelope } from '../../lib/api/types'
import { METHOD_RADIO_LABEL } from '../../lib/methods'
import type { HeadingLevel } from '../Heading/headingLevel'
import { ComparisonReceipts } from '../EvidenceReceipts/ComparisonReceipts'
import { TeamCaseReceipts } from '../EvidenceReceipts/TeamCaseReceipts'
import { ShareButton } from '../ShareButton/ShareButton'
import { VerdictError } from '../VerdictError/VerdictError'
import styles from './VerdictCard.module.css'

export interface VerdictCardProps {
  state: VerdictCardState
  /** Re-submits the same question with a different, known-good year (unknown_year only). */
  onSelectYear?: (year: number) => void
  /** Re-submits the same question with the exact resolved team name (ambiguous_team only). */
  onSelectCandidate?: (candidate: string) => void
  /**
   * The absolute share link for the verdict on screen (issue #184). When set,
   * a success card ends with a "Share this verdict" button; loading and error
   * states never offer one, since there is no verdict to share.
   */
  shareUrl?: string
  /**
   * The level of the receipts' section headings (issue #219), from where
   * the card sits in its page's outline. Defaults to 2, right under an h1.
   */
  headingLevel?: HeadingLevel
}

/**
 * Renders the persona's narration text plus the evidence "receipts"
 * underneath (PRD §3 / Architecture Brief §4.3's "show your work"), or one
 * of the loading/error states while there's no verdict to show yet.
 *
 * A verdict names the engine that answered it (issue #154), read off the
 * response envelope's echoed `method` -- never off the form, whose Engine
 * toggle may already be set for the next question.
 */
export function VerdictCard({
  state,
  onSelectYear,
  onSelectCandidate,
  shareUrl,
  headingLevel = 2,
}: VerdictCardProps) {
  if (state.status === 'loading') {
    return (
      <p role="status" className={styles.loading}>
        Getting the verdict…
      </p>
    )
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
    <article className={styles.vcard}>
      <span aria-hidden="true" className={styles.stamp}>
        <span>Certified</span>
        <span>Verdict</span>
      </span>
      <div className={styles.tear} />
      <blockquote className={styles.narration}>
        {envelope.narration.text}
      </blockquote>
      {envelope.narration.contested && (
        <p className={styles.contested}>
          <span className={styles.tagContested}>Contested</span>
          This one's contested -- reasonable people disagree.
        </p>
      )}
      <p className={styles.engine}>
        {`Engine: ${METHOD_RADIO_LABEL[envelope.evidence.method]}`}
      </p>
      {isTeamCaseEnvelope(envelope) ? (
        <TeamCaseReceipts
          evidence={envelope.evidence}
          headingLevel={headingLevel}
        />
      ) : (
        <ComparisonReceipts
          evidence={envelope.evidence}
          headingLevel={headingLevel}
        />
      )}
      {shareUrl !== undefined && <ShareButton url={shareUrl} />}
    </article>
  )
}
