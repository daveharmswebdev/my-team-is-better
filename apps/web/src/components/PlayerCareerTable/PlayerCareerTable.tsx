import { useId } from 'react'
import type {
  PlayerCareerTotalsOut,
  PlayerSeasonLineOut,
  PlayerStatsOut,
  StarterRecordOut,
} from '../../lib/api/types'
import { formatRecord } from '../../lib/formatRecord'
import type { TableStatColumn } from '../../lib/playerStats'
import {
  DASH,
  LEADER_COLUMN_NOTES,
  NONE_LABEL,
  NOT_RECORDED,
  formatStat,
  leaderColumnNoteId,
  leaderStatCell,
  showsStarterRecord,
  statColumnNotes,
  statColumnsFor,
  undercountNote,
} from '../../lib/playerStats'
import styles from './PlayerCareerTable.module.css'

export interface PlayerCareerTableProps {
  /** Names the table, e.g. "Kurt Warner, regular season". */
  caption: string
  /** This table's season lines, in the API's order. */
  lines: PlayerSeasonLineOut[]
  /** The API's career totals for this season type, or `null` for no totals row. */
  totals: PlayerCareerTotalsOut | null
  /** The id of the note that explains the records (the pulled-early starter note). */
  describedBy?: string
}

function statCellClass(value: number | null): string | undefined {
  return value === null
    ? `${styles.numeric} ${styles.notRecorded}`
    : styles.numeric
}

/**
 * One stat cell: the value, "not recorded", or -- for a value that can't
 * exist, like the longest field goal of a player who never made one -- a
 * `DASH` that assistive tech reads as `NONE_LABEL`.
 */
function StatCell({
  stats,
  statKey,
}: {
  stats: PlayerStatsOut
  statKey: keyof PlayerStatsOut
}) {
  const cell = leaderStatCell(stats, statKey)
  switch (cell.kind) {
    case 'value':
      return <td className={styles.numeric}>{cell.text}</td>
    case 'not-recorded':
      return (
        <td className={`${styles.numeric} ${styles.notRecorded}`}>
          {NOT_RECORDED}
        </td>
      )
    case 'none':
      return (
        <td className={`${styles.numeric} ${styles.notRecorded}`}>
          <span aria-hidden="true">{DASH}</span>
          <span className={styles.srOnly}>{NONE_LABEL}</span>
        </td>
      )
  }
}

/** Games, record, starts and every shown stat: the cells a season line and the totals share. */
function SharedCells({
  games,
  record,
  stats,
  columns,
  showsRecord,
}: Pick<PlayerSeasonLineOut, 'games' | 'record' | 'stats'> & {
  columns: readonly TableStatColumn[]
  showsRecord: boolean
}) {
  return (
    <>
      <td className={statCellClass(games)}>{formatStat(games)}</td>
      {showsRecord && (
        <>
          <td className={styles.numeric}>{recordText(record)}</td>
          <td className={styles.numeric}>{formatStat(record.starts)}</td>
        </>
      )}
      {columns.map((column) => (
        <StatCell key={column.key} stats={stats} statKey={column.key} />
      ))}
    </>
  )
}

/**
 * A stat column's header. An abbreviation ("INT") shows as itself, titled
 * for the mouse, and is named in full for assistive tech; a column a note
 * covers carries the note's marker, hidden from assistive tech, which hears
 * the note itself through `aria-describedby`.
 */
function StatHeader({
  column,
  noteIdPrefix,
}: {
  column: TableStatColumn
  noteIdPrefix: string
}) {
  const { label, fullLabel, note } = column
  return (
    <th
      scope="col"
      className={styles.numeric}
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

function recordText(record: StarterRecordOut): string {
  return formatRecord(record.wins, record.losses, record.ties)
}

/**
 * One season type of a player's career (issue #296): a row per season line
 * as the API sent it, then the API's career totals. A line whose teams played
 * games the source has no stat lines for says so on that line. Sack columns
 * are left out in v1 (#298).
 *
 * The stat columns are the groups the player recorded on these lines
 * (issue #352, `statColumnsFor`): a quarterback's passing and rushing, a
 * receiver's receiving, a kicker's kicking, and so on. The starter record
 * and starts show only for a player who passed or started at quarterback.
 * Defense columns bring the founder's notes (#316) with them, under the
 * table, and each covered header is described by its note.
 */
export function PlayerCareerTable({
  caption,
  lines,
  totals,
  describedBy,
}: PlayerCareerTableProps) {
  const captionId = useId()
  const noteIdPrefix = useId()
  const all = totals === null ? lines : [...lines, totals]
  const columns = statColumnsFor(all.map((line) => line.stats))
  const showsRecord = showsStarterRecord(all)
  const notes = statColumnNotes(columns)
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
              <th scope="col">Season</th>
              <th scope="col">Teams</th>
              <th scope="col" className={styles.numeric}>
                Games
              </th>
              {showsRecord && (
                <>
                  <th scope="col" className={styles.numeric}>
                    Starter record
                  </th>
                  <th scope="col" className={styles.numeric}>
                    Starts
                  </th>
                </>
              )}
              {columns.map((column) => (
                <StatHeader
                  key={column.key}
                  column={column}
                  noteIdPrefix={noteIdPrefix}
                />
              ))}
            </tr>
          </thead>
          <tbody>
            {lines.map((line) => (
              <tr key={`${line.season}-${line.season_type}`}>
                <th scope="row" className={styles.season}>
                  {line.season}
                </th>
                <td className={styles.teams}>
                  <span
                    className={
                      line.teams.length === 0 ? styles.notRecorded : undefined
                    }
                  >
                    {line.teams.length === 0
                      ? NOT_RECORDED
                      : line.teams.join(', ')}
                  </span>
                  {line.games_without_stat_lines > 0 && (
                    <span className={styles.undercount}>
                      {undercountNote(line.games_without_stat_lines)}
                    </span>
                  )}
                </td>
                <SharedCells
                  games={line.games}
                  record={line.record}
                  stats={line.stats}
                  columns={columns}
                  showsRecord={showsRecord}
                />
              </tr>
            ))}
          </tbody>
          {totals !== null && (
            <tfoot>
              <tr>
                <th scope="row" colSpan={2} className={styles.totals}>
                  Career, {totals.seasons}{' '}
                  {totals.seasons === 1 ? 'season' : 'seasons'}
                </th>
                <SharedCells
                  games={totals.games}
                  record={totals.record}
                  stats={totals.stats}
                  columns={columns}
                  showsRecord={showsRecord}
                />
              </tr>
            </tfoot>
          )}
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
