import { useEffect, useId, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { LeaderCategorySelect } from '../../components/LeaderCategorySelect/LeaderCategorySelect'
import { Pager } from '../../components/Pager/Pager'
import { PlayerLeadersTable } from '../../components/PlayerLeadersTable/PlayerLeadersTable'
import { PlayerStatsCredit } from '../../components/PlayerStatsCredit/PlayerStatsCredit'
import { SeasonTypeSwitch } from '../../components/SeasonTypeSwitch/SeasonTypeSwitch'
import {
  SERVER_ERROR_COPY,
  VerdictHttpError,
  VerdictNetworkError,
  fetchPlayerLeaders,
} from '../../lib/api/client'
import type {
  PlayerLeaderCategory,
  PlayerLeaderSort,
  PlayerLeadersOut,
  PlayerSeasonType,
} from '../../lib/api/types'
import {
  LEADER_BOARD_COLUMNS,
  NOT_RECORDED_DISCLOSURE,
  STARTER_RECORD_NOTE,
  UNDERCOUNT_DISCLOSURE,
} from '../../lib/playerStats'
import { usePlayerStatsCredit } from '../usePlayerStatsCredit'
import type { LeadersView } from './leadersSearch'
import {
  parseLeadersSearch,
  toLeadersSearch,
  withCategory,
} from './leadersSearch'
import styles from './PlayerLeadersPage.module.css'

/** Rows per page: the API's own default `limit`. */
const PAGE_SIZE = 50

/** The latest answer, tagged with the URL state it answers. */
type Answer =
  | { key: string; status: 'success'; leaders: PlayerLeadersOut }
  | { key: string; status: 'error'; message: string }

function errorMessage(error: unknown): string {
  // Both carry plain narrator copy, never a raw status (issue #215).
  return error instanceof VerdictNetworkError ||
    error instanceof VerdictHttpError
    ? error.message
    : SERVER_ERROR_COPY
}

/**
 * NFL career leaders (issue #296, #312): who threw for the most, threw the
 * most touchdowns, won the most as a starter, or -- on the rushing board --
 * ran for the most yards, the most touchdowns or carried it most often. The
 * API sorts, ranks and pages; this page renders what it sends and keeps the
 * stat category, season type, sort and offset in the URL, so a shared link, a
 * reload and the Back button all show the same table.
 *
 * Pages own composition/data-fetching; components do not import from pages
 * (enforced by dependency-cruiser -- see .dependency-cruiser.cjs).
 */
export function PlayerLeadersPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const view = parseLeadersSearch(searchParams)
  const { category, season_type: seasonType, sort, offset } = view
  const key = toLeadersSearch(view).toString()
  const [answer, setAnswer] = useState<Answer | null>(null)
  const credit = usePlayerStatsCredit()
  const noteId = useId()

  useEffect(() => {
    // Every URL change asks again; an answer for a URL since left is dropped.
    let cancelled = false
    const requestKey = toLeadersSearch({
      category,
      season_type: seasonType,
      sort,
      offset,
    }).toString()
    fetchPlayerLeaders({
      category,
      season_type: seasonType,
      sort,
      limit: PAGE_SIZE,
      offset,
    })
      .then((leaders) => {
        if (!cancelled) {
          setAnswer({ key: requestKey, status: 'success', leaders })
        }
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setAnswer({
            key: requestKey,
            status: 'error',
            message: errorMessage(error),
          })
        }
      })
    return () => {
      cancelled = true
    }
  }, [category, seasonType, sort, offset])

  const pending = answer?.key !== key

  /** Pushes a history entry, so Back returns to the table before. */
  function show(next: LeadersView) {
    setSearchParams(toLeadersSearch(next))
  }

  function handleSort(nextSort: PlayerLeaderSort) {
    if (nextSort !== sort) {
      show({ ...view, sort: nextSort, offset: 0 })
    }
  }

  function handleCategory(nextCategory: PlayerLeaderCategory) {
    if (nextCategory !== category) {
      // The old sort belongs to the old category, and the two boards have
      // different populations -- `withCategory` resets both.
      show(withCategory(view, nextCategory))
    }
  }

  function handleSeasonType(nextSeasonType: PlayerSeasonType) {
    show({ ...view, season_type: nextSeasonType, offset: 0 })
  }

  function handlePage(nextOffset: number) {
    show({ ...view, offset: nextOffset })
  }

  // The last good table stays up while the next one loads, so a pressed
  // header or pager button keeps its focus.
  const leaders = answer?.status === 'success' ? answer.leaders : null
  const failed = answer?.status === 'error' && !pending ? answer : null
  // The board on screen, which during a switch is still the previous one.
  // The starter-record note explains a column only the passing board has, so
  // it follows the board rather than the requested category.
  const showsRecord =
    LEADER_BOARD_COLUMNS[leaders?.category ?? category].showsRecord

  return (
    <main className={styles.wrap}>
      <h1 className={styles.title}>NFL Leaders</h1>
      <p className={styles.lede}>
        Career passing and rushing totals for every NFL player with stat lines
        in the source. Pick a stat category, then a column to rank by.
      </p>

      <div className={styles.controls}>
        <LeaderCategorySelect value={category} onChange={handleCategory} />
        <SeasonTypeSwitch value={seasonType} onChange={handleSeasonType} />
      </div>

      <section className={styles.notes} aria-labelledby={`${noteId}-heading`}>
        <h2 id={`${noteId}-heading`} className={styles.notesHeading}>
          About these numbers
        </h2>
        {showsRecord && <p id={noteId}>{STARTER_RECORD_NOTE}</p>}
        <p>{UNDERCOUNT_DISCLOSURE}</p>
        <p>{NOT_RECORDED_DISCLOSURE}</p>
      </section>

      <p role="status" className={styles.status}>
        {pending ? 'Loading the leaders…' : ''}
      </p>

      {failed !== null ? (
        <p role="alert" className={styles.error}>
          {failed.message}
        </p>
      ) : (
        leaders !== null && (
          <LeadersBoard
            leaders={leaders}
            busy={pending}
            describedBy={
              LEADER_BOARD_COLUMNS[leaders.category].showsRecord
                ? noteId
                : undefined
            }
            onSort={handleSort}
            onPage={handlePage}
          />
        )
      )}

      <PlayerStatsCredit credit={credit} />
    </main>
  )
}

function LeadersBoard({
  leaders,
  busy,
  describedBy,
  onSort,
  onPage,
}: {
  leaders: PlayerLeadersOut
  busy: boolean
  /** The starter-record note, on the boards that show records. */
  describedBy: string | undefined
  onSort: (sort: PlayerLeaderSort) => void
  onPage: (offset: number) => void
}) {
  if (leaders.rows.length === 0) {
    return leaders.total === 0 ? (
      <p className={styles.empty}>No NFL player stats are loaded yet.</p>
    ) : (
      <div className={styles.empty}>
        <p>Nobody this far down the list.</p>
        <button
          type="button"
          className={styles.topButton}
          onClick={() => {
            onPage(0)
          }}
        >
          Back to the top
        </button>
      </div>
    )
  }
  return (
    <div className={styles.board}>
      <PlayerLeadersTable
        leaders={leaders}
        onSort={onSort}
        busy={busy}
        describedBy={describedBy}
      />
      <Pager
        label="Leaders pages"
        offset={leaders.offset}
        limit={leaders.limit}
        shown={leaders.rows.length}
        total={leaders.total}
        onPage={onPage}
      />
    </div>
  )
}
