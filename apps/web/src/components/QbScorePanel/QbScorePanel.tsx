import { useId } from 'react'
import type {
  PlayerQbScoreComparisonOut,
  QbScoreSide,
} from '../../lib/api/types'
import {
  QB_NARRATION_LOADING_COPY,
  formatQbScore,
  qbFloorLine,
  qbInconclusiveCopy,
  qbMeasureEdge,
} from '../../lib/qbScore'
import type { QbMeasure } from '../../lib/qbScore'
import { QbScoreExplanation } from '../QbScoreExplanation/QbScoreExplanation'
import styles from './QbScorePanel.module.css'

/**
 * Where the narration of `POST /api/players/compare/verdict` stands. The
 * page owns the request; the panel only shows what it is told. `text` is
 * rendered as sent and never parsed; `message` is already the narrator's
 * line (`qbNarrationErrorCopy`).
 */
export type QbNarrationState =
  | { status: 'loading' }
  | { status: 'success'; text: string }
  | { status: 'error'; message: string }

export interface QbScorePanelProps {
  /** `GET /api/players/compare`'s `qb_score`: the panel renders from it alone. */
  qbScore: PlayerQbScoreComparisonOut
  /** The db's first season of player stats (1999): the score's floor. */
  dataFirstSeason: number | null
  /** Each side's `coverage.cut_off`: his career began before the data. */
  cutOff: Record<QbScoreSide, boolean>
  narration: QbNarrationState
}

const MEASURES: readonly [QbMeasure, string][] = [
  ['career', 'Career'],
  ['peak', 'Peak'],
]

/**
 * The era-adjusted QB score for two quarterbacks (issue #459, epic #439):
 * career and peak, each with the winner and margin the API names -- never a
 * winner worked out here -- the floor the score counts from, how it was got
 * (`QbScoreExplanation`), and the bar-stool narration.
 *
 * The verdict leads (issue #474): the winning line (each measure's edge,
 * as the table's Edge column states it) or the inconclusive line, then the
 * take; the lede, the floor, the table and the explanation follow.
 *
 * The score renders from the comparison's `qb_score` without waiting for the
 * narration, which arrives after in a polite live region, and a narration
 * failure only changes that region: the score stays up.
 */
export function QbScorePanel({
  qbScore,
  dataFirstSeason,
  cutOff,
  narration,
}: QbScorePanelProps) {
  const id = useId()
  const headingId = `${id}-heading`
  const takeId = `${id}-take`
  const inconclusive = qbInconclusiveCopy(qbScore)
  const cutOffNames = (['a', 'b'] as const)
    .filter((side) => cutOff[side])
    .map((side) => qbScore[side].display_name)
  const floor = qbFloorLine(dataFirstSeason, cutOffNames)
  const { a, b } = qbScore

  return (
    <section className={styles.panel} aria-labelledby={headingId}>
      <h2 id={headingId} className={styles.heading}>
        QB score
      </h2>

      {/* The verdict first (#474): the API's winner on each measure -- the
          same words as the table's Edge column -- or why there is none. */}
      {inconclusive !== null ? (
        <p className={styles.inconclusive}>{inconclusive}</p>
      ) : (
        <p className={styles.winningLine}>
          {MEASURES.map(
            ([measure, label]) =>
              `${label}: ${qbMeasureEdge(qbScore, measure)}`,
          ).join(' · ')}
        </p>
      )}

      {/* The narrator explains right under the winner; the working after. */}
      <section
        className={styles.take}
        aria-labelledby={takeId}
        aria-live="polite"
        aria-busy={narration.status === 'loading'}
      >
        <h3 id={takeId} className={styles.takeHeading}>
          The take
        </h3>
        {narration.status === 'loading' && (
          <p className={styles.loading}>{QB_NARRATION_LOADING_COPY}</p>
        )}
        {narration.status === 'success' && (
          <p className={styles.narration}>{narration.text}</p>
        )}
        {narration.status === 'error' && (
          <p className={styles.narrationError}>{narration.message}</p>
        )}
      </section>

      <p className={styles.lede}>
        Era-adjusted efficiency: every season rated per play against the
        quarterbacks of that same season.
      </p>
      {floor !== null && (
        <p className={styles.floor}>
          {cutOffNames.length > 0 ? (
            <strong className={styles.loud}>{floor}</strong>
          ) : (
            floor
          )}
        </p>
      )}

      {inconclusive === null && (
        <table className={styles.table}>
          <caption className={styles.caption}>
            QB score, {a.display_name} and {b.display_name}
          </caption>
          <thead>
            <tr>
              <th scope="col">Measure</th>
              <th scope="col" className={styles.numeric}>
                {a.display_name}
              </th>
              <th scope="col" className={styles.numeric}>
                {b.display_name}
              </th>
              <th scope="col">Edge</th>
            </tr>
          </thead>
          <tbody>
            {MEASURES.map(([measure, label]) => {
              const winner =
                measure === 'career'
                  ? qbScore.career_winner
                  : qbScore.peak_winner
              return (
                <tr key={measure}>
                  <th scope="row">{label}</th>
                  <ScoreCell value={a[measure]} won={winner === 'a'} />
                  <ScoreCell value={b[measure]} won={winner === 'b'} />
                  <td className={styles.edge}>
                    {qbMeasureEdge(qbScore, measure)}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}

      <QbScoreExplanation qbScore={qbScore} dataFirstSeason={dataFirstSeason} />
    </section>
  )
}

/** A score as printed, bold where the API named that side the winner. */
function ScoreCell({ value, won }: { value: number | null; won: boolean }) {
  // Conclusive comparisons always carry both scores; a dash is only a guard.
  const text = value === null ? '—' : formatQbScore(value)
  return (
    <td className={won ? `${styles.numeric} ${styles.won}` : styles.numeric}>
      {text}
    </td>
  )
}
