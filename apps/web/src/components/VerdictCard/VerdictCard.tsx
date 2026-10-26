import type {
  ComparisonTeamSummaryOut,
  Method,
  VerdictCardState,
  VerdictEnvelope,
} from '../../lib/api/types'
import { isTeamCaseEnvelope } from '../../lib/api/types'
import { formatRecord } from '../../lib/formatRecord'
import { METHOD_RADIO_LABEL } from '../../lib/methods'
import { useIsWideViewport } from '../../lib/useMediaQuery'
import type { HeadingLevel } from '../Heading/headingLevel'
import { OtherEngineRanks } from '../OtherEngineRanks/OtherEngineRanks'
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
   * Re-submits the same question under another engine (issue #155), from
   * the other engines' ranks line on a success card.
   */
  onSelectMethod?: (method: Method) => void
  /**
   * The absolute share link for the verdict on screen (issue #184). When set,
   * a success card offers one "Share this verdict" button (#474): first in
   * the card on a desktop, floating bottom-right on a phone. Loading and
   * error states never offer one, since there is no verdict to share.
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
 *
 * The order (issue #474): Share (desktop) -> who's compared -> the verdict
 * (stamp, narration, contested, engine) -> the other engines' ranks -> the
 * receipts -> Share (phone, floating). Exactly one Share button renders,
 * chosen by the viewport, so neither layout leaves a hidden twin in the
 * accessibility tree.
 */
export function VerdictCard({
  state,
  onSelectYear,
  onSelectCandidate,
  onSelectMethod,
  shareUrl,
  headingLevel = 2,
}: VerdictCardProps) {
  const isWide = useIsWideViewport()

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
      {shareUrl !== undefined && isWide && (
        <ShareButton url={shareUrl} layout="inline" />
      )}
      <VerdictTeams envelope={envelope} />
      {/* The verdict itself, its own positioned block so the stamp sits on
          the tear between it and the teams. */}
      <div className={styles.verdict}>
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
      </div>
      {/* Issue #155: right under the answering engine's name, and so just
          above its rank in the receipts. */}
      <OtherEngineRanks
        rows={
          isTeamCaseEnvelope(envelope)
            ? [{ ranks: envelope.other_method_ranks }]
            : [
                {
                  teamName: envelope.evidence.team_a.team_name,
                  ranks: envelope.team_a_other_method_ranks,
                },
                {
                  teamName: envelope.evidence.team_b.team_name,
                  ranks: envelope.team_b_other_method_ranks,
                },
              ]
        }
        onSelectMethod={onSelectMethod}
      />
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
      {shareUrl !== undefined && !isWide && (
        <ShareButton url={shareUrl} layout="floating" />
      )}
    </article>
  )
}

/** The fields a team's header line reads: on both `TeamCaseOut` and a comparison side. */
type TeamLineFields = Pick<
  ComparisonTeamSummaryOut,
  'team_name' | 'rank' | 'wins' | 'losses' | 'ties'
>

/**
 * Who the verdict is about (issue #474): each team's name, then its rank
 * under the answering engine and its record -- both teams of a matchup, the
 * one team of a best-team or case-for-a-team question.
 */
function VerdictTeams({ envelope }: { envelope: VerdictEnvelope }) {
  if (isTeamCaseEnvelope(envelope)) {
    return (
      <p
        className={`${styles.teams} ${styles.oneTeam}`}
        data-testid="verdict-teams"
      >
        <TeamLine team={envelope.evidence} />
      </p>
    )
  }
  const { team_a, team_b } = envelope.evidence
  return (
    <ul
      className={styles.teams}
      aria-label="Teams compared"
      data-testid="verdict-teams"
    >
      {[team_a, team_b].map((team) => (
        <li key={team.team_id} className={styles.team}>
          <TeamLine team={team} />
        </li>
      ))}
    </ul>
  )
}

function TeamLine({ team }: { team: TeamLineFields }) {
  return (
    <>
      <span className={styles.teamName}>{team.team_name}</span>{' '}
      <span className={styles.teamMeta}>
        {`Rank #${team.rank} · ${formatRecord(team.wins, team.losses, team.ties)}`}
      </span>
    </>
  )
}
