import { useId } from 'react'
import type { PlayerCareerTotalsOut } from '../../lib/api/types'
import {
  MARK_GLYPH,
  MARK_SCREEN_READER_TEXT,
  comparisonRows,
} from '../../lib/playerCompare'
import { NOT_RECORDED } from '../../lib/playerStats'
import styles from './PlayerComparisonTable.module.css'

export interface ComparedPlayer {
  name: string
  /** The API's career totals of this table's season type, or `null` for none. */
  totals: PlayerCareerTotalsOut | null
}

export interface PlayerComparisonTableProps {
  /** Names the table, e.g. "Kurt Warner and Steve McNair, regular season". */
  caption: string
  a: ComparedPlayer
  b: ComparedPlayer
  /** What a player's column says when they have no totals of this type. */
  noTotalsCopy: string
  /** The id of the note that explains the records. */
  describedBy?: string
}

function ValueCell({
  value,
  marked,
  firstRow,
  rowCount,
  noTotalsCopy,
}: {
  value: string | null
  marked: boolean
  firstRow: boolean
  rowCount: number
  noTotalsCopy: string
}) {
  if (value === null) {
    // No totals of this type: one cell down the whole column says so.
    return firstRow ? (
      <td rowSpan={rowCount} className={styles.noTotals}>
        {noTotalsCopy}
      </td>
    ) : null
  }
  const classes = [styles.numeric]
  if (value === NOT_RECORDED) {
    classes.push(styles.notRecorded)
  }
  if (marked) {
    classes.push(styles.marked)
  }
  return (
    <td className={classes.join(' ')}>
      {value}
      {marked && (
        <>
          {' '}
          <span aria-hidden="true" className={styles.glyph}>
            {MARK_GLYPH}
          </span>
          <span className={styles.srOnly}> {MARK_SCREEN_READER_TEXT}</span>
        </>
      )}
    </td>
  )
}

/**
 * Two players' career totals of one season type, side by side (issue #301):
 * a column per player, a row per total. In each row the larger of two
 * recorded, unequal numbers is marked, with a glyph and with words a screen
 * reader announces. Nothing is added up, averaged or declared.
 */
export function PlayerComparisonTable({
  caption,
  a,
  b,
  noTotalsCopy,
  describedBy,
}: PlayerComparisonTableProps) {
  const captionId = useId()
  const rows = comparisonRows(a.totals, b.totals)
  return (
    <div
      className={styles.scroll}
      role="region"
      aria-labelledby={captionId}
      // Focusable, so a keyboard user can scroll a table wider than the screen.
      tabIndex={0}
    >
      <table className={styles.table} aria-describedby={describedBy}>
        <caption id={captionId} className={styles.caption}>
          {caption}
        </caption>
        <thead>
          <tr>
            <th scope="col">Total</th>
            <th scope="col" className={styles.numeric}>
              {a.name}
            </th>
            <th scope="col" className={styles.numeric}>
              {b.name}
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={row.key}>
              <th scope="row" className={styles.label}>
                {row.label}
              </th>
              <ValueCell
                value={row.a}
                marked={row.marked === 'a'}
                firstRow={index === 0}
                rowCount={rows.length}
                noTotalsCopy={noTotalsCopy}
              />
              <ValueCell
                value={row.b}
                marked={row.marked === 'b'}
                firstRow={index === 0}
                rowCount={rows.length}
                noTotalsCopy={noTotalsCopy}
              />
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
