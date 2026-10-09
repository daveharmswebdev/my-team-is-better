import { useId } from 'react'
import { Link } from 'react-router-dom'
import type {
  PlayerLeaderSort,
  PlayerLeadersOut,
  PlayerStatsOut,
} from '../../lib/api/types'
import { formatRecord } from '../../lib/formatRecord'
import type {
  LeaderColumnNote,
  LeaderStatColumn,
  LeaderStatKey,
} from '../../lib/playerStats'
import {
  DASH,
  LEADER_COLUMN_NOTES,
  NONE_LABEL,
  NOT_RECORDED,
  SEASON_TYPE_LABEL,
  SORT_LABEL,
  formatSeasonSpan,
  formatStat,
  leaderBoardColumns,
  leaderColumnNotes,
  leaderStatCell,
  sortForStat,
} from '../../lib/playerStats'
import styles from './PlayerLeadersTable.module.css'

export interface PlayerLeadersTableProps {
  /** One page, exactly as the API sent it: rows, ranks and sort are rendered, never recomputed. */
  leaders: PlayerLeadersOut
  /** A sortable header was pressed. Always descending, so there is no direction. */
  onSort: (sort: PlayerLeaderSort) => void
  /** A new page is on its way; the table stays up, so a header keeps focus. */
  busy?: boolean
  /** The id of the note that explains this board: the pulled-early starter note, or the FG% minimum. */
  describedBy?: string
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
 * A header's text (issue #317). An abbreviation shows as itself, titled for
 * the mouse, and is named in full for assistive tech; a column a note covers
 * carries that note's marker, hidden from assistive tech, which gets the
 * note itself through `aria-describedby` instead.
 */
function HeaderLabel({
  label,
  fullLabel,
  marker,
}: {
  label: string
  fullLabel: string | undefined
  marker: string | undefined
}) {
  return (
    <>
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
      {marker !== undefined && (
        <span className={styles.marker} aria-hidden="true">
          {marker}
        </span>
      )}
    </>
  )
}

/** How a stat header reads, and which note (by element id) describes it. */
interface HeaderText {
  label: string
  fullLabel: string | undefined
  marker: string | undefined
  describedBy: string | undefined
}

/**
 * A sortable column header: a button inside the `th`, with `aria-sort` on
 * the `th` itself, where assistive tech reads it. A column a note covers
 * describes its button by that note, so the note is read where the column
 * is reached.
 */
function SortHeader({
  text,
  sort,
  current,
  onSort,
}: {
  text: HeaderText
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
        aria-describedby={text.describedBy}
        onClick={() => {
          onSort(sort)
        }}
      >
        <HeaderLabel
          label={text.label}
          fullLabel={text.fullLabel}
          marker={text.marker}
        />
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
 * One stat cell, as `leaderStatCell` decides it. A value that cannot exist
 * (no longest kick, no FG% without an attempt) shows `DASH`, which assistive
 * tech skips in favour of `NONE_LABEL` -- a bare dash is read as nothing, or
 * as "minus".
 */
function StatCell({
  stats,
  statKey,
}: {
  stats: PlayerStatsOut
  statKey: LeaderStatKey
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

/**
 * The NFL career leaderboard (issue #296): one page of rows in the API's
 * order, with the API's competition ranks (ties shared), sortable by the
 * columns the API sorts on. A stat the source didn't track reads "not
 * recorded". Sack columns are left out in v1 (#298).
 *
 * Which columns those are is the API's `category` (issue #312), not this
 * component's guesswork: the passing board carries the starter record and
 * the passing stats, the rushing board the three rushing ones, the
 * receiving board (#314) receptions, receiving yards and TDs, and the
 * kicking and punting boards (#315) their own. All come from
 * `LEADER_BOARD_COLUMNS`, and a column is sortable exactly when the
 * category sorts on it (`sortForStat`), so the headers can't offer a sort
 * the API would refuse. The kicking board's FG% and 50+ are the one
 * exception to rendering only what was sent: the API ranks by them without
 * sending them, so `deriveKickingStats` computes each row's value -- never
 * its rank or its place.
 *
 * The defense board (#317) shows sacks to one decimal, and under the table
 * the founder's notes (#316) for the columns that need one: each note is
 * read off the columns (`leaderColumnNotes`), marked on the headers it
 * covers and tied to them with `aria-describedby`, so no board can show
 * those numbers without it.
 */
export function PlayerLeadersTable({
  leaders,
  onSort,
  busy = false,
  describedBy,
}: PlayerLeadersTableProps) {
  const captionId = useId()
  const noteIdPrefix = useId()
  const caption = `NFL career leaders: ${SEASON_TYPE_LABEL[leaders.season_type].toLowerCase()}, by ${SORT_LABEL[leaders.sort]}`
  const { showsRecord, stats: statColumns } = leaderBoardColumns(
    leaders.category,
  )
  const notes = leaderColumnNotes(leaders.category)
  const noteId = (note: LeaderColumnNote) => `${noteIdPrefix}-${note}`

  function headerText(column: LeaderStatColumn): HeaderText {
    return {
      label: column.label,
      fullLabel: column.fullLabel,
      marker:
        column.note === undefined
          ? undefined
          : LEADER_COLUMN_NOTES[column.note].marker,
      describedBy: column.note === undefined ? undefined : noteId(column.note),
    }
  }

  return (
    <>
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
              {showsRecord && (
                <>
                  <SortHeader
                    text={{
                      label: 'Starter record',
                      fullLabel: undefined,
                      marker: undefined,
                      describedBy: undefined,
                    }}
                    sort="wins"
                    current={leaders.sort}
                    onSort={onSort}
                  />
                  <th scope="col" className={styles.numeric}>
                    Starts
                  </th>
                </>
              )}
              {statColumns.map((column) => {
                const sort = sortForStat(leaders.category, column.key)
                const text = headerText(column)
                return sort === undefined ? (
                  <th
                    scope="col"
                    className={styles.numeric}
                    key={column.key}
                    aria-describedby={text.describedBy}
                  >
                    <HeaderLabel
                      label={text.label}
                      fullLabel={text.fullLabel}
                      marker={text.marker}
                    />
                  </th>
                ) : (
                  <SortHeader
                    key={column.key}
                    text={text}
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
                {showsRecord && (
                  <>
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
                  </>
                )}
                {statColumns.map((column) => (
                  <StatCell
                    key={column.key}
                    stats={row.stats}
                    statKey={column.key}
                  />
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {notes.length > 0 && (
        <div className={styles.notes}>
          {notes.map((note) => (
            <p key={note}>
              <span className={styles.marker} aria-hidden="true">
                {LEADER_COLUMN_NOTES[note].marker}
              </span>{' '}
              <span id={noteId(note)}>{LEADER_COLUMN_NOTES[note].text}</span>
            </p>
          ))}
        </div>
      )}
    </>
  )
}
