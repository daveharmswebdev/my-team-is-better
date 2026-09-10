import type { ComparisonResultOut } from '../../lib/api/types'
import styles from './ComparisonReceipts.module.css'

export interface ComparisonReceiptsProps {
  evidence: ComparisonResultOut
}

/**
 * Renders a loosely-typed `Record<string, unknown>` as a label/value list.
 * `team_a`/`team_b`/`head_to_head`/`common_opponents` are `dict[str, object]`
 * on the Python side too -- there is no tighter contract to render against
 * (see `apps/api/src/api/models.py`), so this stays generic rather than
 * inventing bespoke structure.
 */
function KeyValueList({ record }: { record: Record<string, unknown> }) {
  return (
    <dl className={styles.kvGrid}>
      {Object.entries(record).map(([key, value]) => (
        <div key={key}>
          <dt>{key}</dt>
          <dd>
            {typeof value === 'object' ? JSON.stringify(value) : String(value)}
          </dd>
        </div>
      ))}
    </dl>
  )
}

/** The "receipts" for a compare verdict (PRD §3 / Architecture Brief §4.3's "show your work"). */
export function ComparisonReceipts({ evidence }: ComparisonReceiptsProps) {
  return (
    <section aria-label="comparison evidence" className={styles.receipts}>
      <h4 className={styles.label}>Team A</h4>
      <KeyValueList record={evidence.team_a} />

      <h4 className={styles.label}>Team B</h4>
      <KeyValueList record={evidence.team_b} />

      <h4 className={styles.label}>Head to head</h4>
      <KeyValueList record={evidence.head_to_head} />

      <h4 className={styles.label}>Common opponents</h4>
      {evidence.common_opponents.length > 0 ? (
        <ul className={styles.list}>
          {evidence.common_opponents.map((opponent, index) => (
            // Index-as-key: these are loosely-typed dicts with no stable id
            // field guaranteed by the backend contract, and the list is
            // render-only (never reordered/filtered client-side).
            <li key={index}>
              <KeyValueList record={opponent} />
            </li>
          ))}
        </ul>
      ) : (
        <p className={styles.empty}>No common opponents.</p>
      )}

      <p className={styles.verdictLine}>
        Rating diff: {evidence.rating_diff.toFixed(2)}
      </p>
      <p>{evidence.verdict}</p>
    </section>
  )
}
