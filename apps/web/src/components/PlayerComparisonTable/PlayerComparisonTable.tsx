import { useId } from 'react'
import type {
  PlayerCareerTotalsOut,
  PlayerPositionGroup,
} from '../../lib/api/types'
import type { ComparisonRow } from '../../lib/playerCompare'
import {
  MARK_GLYPH,
  MARK_SCREEN_READER_TEXT,
  comparisonRows,
} from '../../lib/playerCompare'
import {
  DASH,
  LEADER_COLUMN_NOTES,
  NONE_LABEL,
  NOT_RECORDED,
  leaderColumnNoteId,
  statColumnNotes,
} from '../../lib/playerStats'
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
  /**
   * The position group both players share (`comparisonGroup`), which
   * decides the rows (#438); `null` falls back to the stats they recorded.
   */
  group: PlayerPositionGroup | null
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
  if (value === NOT_RECORDED || value === DASH) {
    classes.push(styles.notRecorded)
  }
  if (marked) {
    classes.push(styles.marked)
  }
  return (
    <td className={classes.join(' ')}>
      {value === DASH ? (
        // A value that can't exist (no longest kick): a bare dash is read
        // as nothing, or as "minus", so assistive tech hears "none".
        <>
          <span aria-hidden="true">{DASH}</span>
          <span className={styles.srOnly}>{NONE_LABEL}</span>
        </>
      ) : (
        value
      )}
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
 * A row's header. An abbreviation ("INT") shows as itself, titled for the
 * mouse, and is named in full for assistive tech; a row a note covers
 * carries the note's marker, and is described by the note itself.
 */
function RowHeader({
  row,
  noteIdPrefix,
}: {
  row: ComparisonRow
  noteIdPrefix: string
}) {
  const { label, fullLabel, note } = row
  return (
    <th
      scope="row"
      className={styles.label}
      aria-describedby={
        note === undefined ? undefined : leaderColumnNoteId(noteIdPrefix, note)
      }
    >
      {fullLabel === undefined ? (
        label
      ) : (
        <>
          <abbr className={styles.abbr} title={fullLabel} aria-hidden="true">
            {label}
          </abbr>
          <span className={styles.srOnly}>{fullLabel}</span>
        </>
      )}
      {note !== undefined && (
        <span className={styles.marker} aria-hidden="true">
          {LEADER_COLUMN_NOTES[note].marker}
        </span>
      )}
    </th>
  )
}

/**
 * Two players' career totals of one season type, side by side (issue #301):
 * a column per player, a row per total. In each row the larger of two
 * recorded, unequal numbers is marked, with a glyph and with words a screen
 * reader announces. Nothing is added up, averaged or declared.
 *
 * The rows come from the position group both players share (issue #438):
 * two backs are compared on rushing then receiving, two receivers on
 * receiving, whatever else either recorded. A pair with no shared group
 * gets the stat groups either player recorded (#352); defense rows bring
 * the founder's notes (#316) with them, under the table.
 */
export function PlayerComparisonTable({
  caption,
  a,
  b,
  group,
  noTotalsCopy,
  describedBy,
}: PlayerComparisonTableProps) {
  const captionId = useId()
  const noteIdPrefix = useId()
  const rows = comparisonRows(a.totals, b.totals, group)
  const notes = statColumnNotes(rows)
  return (
    <>
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
                <RowHeader row={row} noteIdPrefix={noteIdPrefix} />
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
      {notes.map((note) => (
        <p key={note} className={styles.note}>
          <span className={styles.marker} aria-hidden="true">
            {LEADER_COLUMN_NOTES[note].marker}
          </span>{' '}
          <span id={leaderColumnNoteId(noteIdPrefix, note)}>
            {LEADER_COLUMN_NOTES[note].text}
          </span>
        </p>
      ))}
    </>
  )
}
