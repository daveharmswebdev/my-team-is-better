import { formatRating } from '../../lib/formatRating'
import { formatRecord } from '../../lib/formatRecord'
import type {
  Method,
  OpponentCreditOut,
  RatingBreakdownOut,
} from '../../lib/api/types'
import { RatingDisclosureShell } from './RatingDisclosureShell'
import styles from './RatingBreakdownDisclosure.module.css'

export interface RatingBreakdownDisclosureProps {
  /** Team this breakdown belongs to (used in labels only, not rendered as a heading of its own). */
  teamName: string
  /** The rating method behind `rating`/`breakdown` -- picks every number's display scale via `formatRating`. */
  method: Method
  /** The same rating value `ComparisonReceipts` already displays -- shown again in the footer total so a fan can see it's consistent with the entries + residual below it. */
  rating: number
  breakdown: RatingBreakdownOut
}

/**
 * Per-opponent record for a breakdown row. The engine's per-opponent credit
 * carries `games_played`/`wins`/`losses` but no `ties` field (issue #83), so
 * ties are *derived* here as the games that were neither a win nor a loss --
 * the same arithmetic the engine's own explanation text uses (e.g. "Played
 * them 2 times (1-0-1)"). Clamped at 0 so a malformed entry can never render
 * a negative tie count.
 */
function opponentRecord(entry: OpponentCreditOut): string {
  const derivedTies = Math.max(
    0,
    entry.games_played - entry.wins - entry.losses,
  )
  return formatRecord(entry.wins, entry.losses, derivedTies)
}

/**
 * Hover popover (desktop) / tap modal (mobile) anchored to a team's rating
 * value, showing the per-opponent Keener credit breakdown behind it
 * (issue #31). `residual_contribution` is real math (a fixed connectivity
 * regularizer plus the credit matrix's dominant eigenvalue being below 1),
 * typically ~47-53% of a team's rating -- it is labeled as its own named
 * thing ("Rating-system baseline"), never folded into "other"/rounding.
 * The trigger/popover/modal plumbing is `RatingDisclosureShell`'s.
 *
 * Keener-only copy: callers render this only for a method whose
 * `RATING_BREAKDOWN_BY_METHOD` entry is the Keener breakdown (issues #153,
 * #183). Under Elo it would claim "Total 0" matches a rating of 1,684.
 */
export function RatingBreakdownDisclosure({
  teamName,
  method,
  rating,
  breakdown,
}: RatingBreakdownDisclosureProps) {
  const entriesTotal = breakdown.entries.reduce(
    (sum, entry) => sum + entry.contribution,
    0,
  )
  const total = entriesTotal + breakdown.residual_contribution

  return (
    <RatingDisclosureShell
      triggerLabel={formatRating(rating, method)}
      title={`${teamName} rating breakdown`}
      closeLabel="Close rating breakdown"
    >
      <h6 className={styles.sectionLabel}>Credit by opponent</h6>
      {breakdown.entries.length > 0 ? (
        <ul className={styles.rows}>
          {breakdown.entries.map((entry) => (
            <li key={entry.opponent_team_id} className={styles.row}>
              <span className={styles.rowOpponent}>{entry.opponent_name}</span>
              <span className={styles.rowRecord}>{opponentRecord(entry)}</span>
              <span className={styles.rowNum}>
                {formatRating(entry.credit, method)}
              </span>
              <span className={styles.rowNum}>
                {formatRating(entry.contribution, method)}
              </span>
              <span className={styles.rowExplanation}>{entry.explanation}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p className={styles.empty}>No individual opponent credit.</p>
      )}

      <div className={styles.residualRow}>
        <span className={styles.residualLabel}>Rating-system baseline</span>
        <span className={styles.rowNum}>
          {formatRating(breakdown.residual_contribution, method)}
        </span>
      </div>
      <p className={styles.residualNote}>
        Keener&rsquo;s method gives every team a baseline connectivity credit,
        on top of specific opponents &mdash; this is real math, not a rounding
        error, and it&rsquo;s often close to half a team&rsquo;s rating.
      </p>

      <div className={styles.totalRow}>
        <span>Total</span>
        <span className={styles.rowNum}>{formatRating(total, method)}</span>
      </div>
      <p className={styles.totalNote}>
        Matches the displayed rating: {formatRating(rating, method)}
      </p>
    </RatingDisclosureShell>
  )
}
