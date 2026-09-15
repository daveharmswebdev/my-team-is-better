import { useId } from 'react'
import type {
  PlayerCareerTotalsOut,
  PlayerSeasonLineOut,
  StarterRecordOut,
} from '../../lib/api/types'
import { formatRecord } from '../../lib/formatRecord'
import {
  NOT_RECORDED,
  STAT_COLUMNS,
  formatStat,
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

/** Games, record, starts and every shown stat: the cells a season line and the totals share. */
function SharedCells({
  games,
  record,
  stats,
}: Pick<PlayerSeasonLineOut, 'games' | 'record' | 'stats'>) {
  return (
    <>
      <td className={statCellClass(games)}>{formatStat(games)}</td>
      <td className={styles.numeric}>{recordText(record)}</td>
      <td className={styles.numeric}>{formatStat(record.starts)}</td>
      {STAT_COLUMNS.map((column) => (
        <td key={column.key} className={statCellClass(stats[column.key])}>
          {formatStat(stats[column.key])}
        </td>
      ))}
    </>
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
 */
export function PlayerCareerTable({
  caption,
  lines,
  totals,
  describedBy,
}: PlayerCareerTableProps) {
  const captionId = useId()
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
            <th scope="col">Season</th>
            <th scope="col">Teams</th>
            <th scope="col" className={styles.numeric}>
              Games
            </th>
            <th scope="col" className={styles.numeric}>
              Starter record
            </th>
            <th scope="col" className={styles.numeric}>
              Starts
            </th>
            {STAT_COLUMNS.map((column) => (
              <th scope="col" className={styles.numeric} key={column.key}>
                {column.label}
              </th>
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
              />
            </tr>
          </tfoot>
        )}
      </table>
    </div>
  )
}
