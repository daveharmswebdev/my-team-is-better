import { useId } from 'react'
import { Link } from 'react-router-dom'
import type {
  PlayerLeaderSort,
  PlayerLeadersOut,
  PlayerStatsOut,
} from '../../lib/api/types'
import { formatRecord } from '../../lib/formatRecord'
import {
  NOT_RECORDED,
  SEASON_TYPE_LABEL,
  SORT_LABEL,
  STAT_COLUMNS,
  formatSeasonSpan,
  formatStat,
} from '../../lib/playerStats'
import styles from './PlayerLeadersTable.module.css'

export interface PlayerLeadersTableProps {
  /** One page, exactly as the API sent it: rows, ranks and sort are rendered, never recomputed. */
  leaders: PlayerLeadersOut
  /** A sortable header was pressed. Always descending, so there is no direction. */
  onSort: (sort: PlayerLeaderSort) => void
  /** A new page is on its way; the table stays up, so a header keeps focus. */
  busy?: boolean
  /** The id of the note that explains the records (the pulled-early starter note). */
  describedBy?: string
}

/** The stat columns that re-sort the board. */
const SORT_FOR_STAT: Partial<Record<keyof PlayerStatsOut, PlayerLeaderSort>> = {
  passing_yards: 'passing_yards',
  passing_tds: 'passing_tds',
}

function SortArrow({ active }: { active: boolean }) {
  return (
    <svg
      className={active ? styles.arrowActive : styles.arrow}
      aria-hidden="true"
      focusable="false"
      viewBox="0 0 10 6"
      width="10"
      height="6"
    >
      <path d="M0 0h10L5 6z" />
    </svg>
  )
}

/**
 * A sortable column header: a button inside the `th`, with `aria-sort` on
 * the `th` itself, where assistive tech reads it.
 */
function SortHeader({
  label,
  sort,
  current,
  onSort,
}: {
  label: string
  sort: PlayerLeaderSort
  current: PlayerLeaderSort
  onSort: (sort: PlayerLeaderSort) => void
}) {
  const active = sort === current
  return (
    <th
      scope="col"
      className={styles.numeric}
      aria-sort={active ? 'descending' : 'none'}
    >
      <button
        type="button"
        className={active ? styles.sortActive : styles.sort}
        onClick={() => {
          onSort(sort)
        }}
      >
        {label}
        <SortArrow active={active} />
      </button>
    </th>
  )
}

function statCellClass(value: number | null): string | undefined {
  return value === null
    ? `${styles.numeric} ${styles.notRecorded}`
    : styles.numeric
}

/**
 * The NFL career leaderboard (issue #296): one page of rows in the API's
 * order, with the API's competition ranks (ties shared), sortable by the
 * three columns the API sorts on. A stat the source didn't track reads "not
 * recorded". Sack columns are left out in v1 (#298).
 */
export function PlayerLeadersTable({
  leaders,
  onSort,
  busy = false,
  describedBy,
}: PlayerLeadersTableProps) {
  const captionId = useId()
  const caption = `NFL career leaders: ${SEASON_TYPE_LABEL[leaders.season_type].toLowerCase()}, by ${SORT_LABEL[leaders.sort]}`

  return (
    <div
      className={styles.scroll}
      role="region"
      aria-labelledby={captionId}
      // Focusable, so a keyboard user can scroll a table wider than the screen.
      tabIndex={0}
    >
      <table
        className={styles.table}
        aria-describedby={describedBy}
        aria-busy={busy}
      >
        <caption id={captionId} className={styles.caption}>
          {caption}
        </caption>
        <thead>
          <tr>
            <th scope="col" className={styles.numeric}>
              Rank
            </th>
            <th scope="col">Player</th>
            <th scope="col">Position</th>
            <th scope="col">Seasons</th>
            <th scope="col" className={styles.numeric}>
              Games
            </th>
            <SortHeader
              label="Starter record"
              sort="wins"
              current={leaders.sort}
              onSort={onSort}
            />
            <th scope="col" className={styles.numeric}>
              Starts
            </th>
            {STAT_COLUMNS.map((column) => {
              const sort = SORT_FOR_STAT[column.key]
              return sort === undefined ? (
                <th scope="col" className={styles.numeric} key={column.key}>
                  {column.label}
                </th>
              ) : (
                <SortHeader
                  key={column.key}
                  label={column.label}
                  sort={sort}
                  current={leaders.sort}
                  onSort={onSort}
                />
              )
            })}
          </tr>
        </thead>
        <tbody>
          {leaders.rows.map((row) => (
            <tr key={row.player_id}>
              <td
                className={
                  row.rank === null
                    ? `${styles.numeric} ${styles.notRecorded}`
                    : `${styles.numeric} ${styles.rank}`
                }
              >
                {row.rank === null ? 'not ranked' : row.rank}
              </td>
              <th scope="row" className={styles.player}>
                <Link to={`/nfl/players/${row.player_id}`}>
                  {row.display_name}
                </Link>
              </th>
              <td
                className={
                  row.position === null ? styles.notRecorded : undefined
                }
              >
                {row.position ?? NOT_RECORDED}
              </td>
              <td className={styles.numeric}>
                {formatSeasonSpan(row.first_season, row.last_season)}
              </td>
              <td className={statCellClass(row.games)}>
                {formatStat(row.games)}
              </td>
              <td className={styles.numeric}>
                {formatRecord(
                  row.record.wins,
                  row.record.losses,
                  row.record.ties,
                )}
              </td>
              <td className={styles.numeric}>
                {formatStat(row.record.starts)}
              </td>
              {STAT_COLUMNS.map((column) => (
                <td
                  key={column.key}
                  className={statCellClass(row.stats[column.key])}
                >
                  {formatStat(row.stats[column.key])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
