import { useEffect, useId, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
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
  PlayerLeaderSort,
  PlayerLeadersOut,
  PlayerSeasonType,
} from '../../lib/api/types'
import {
  NOT_RECORDED_DISCLOSURE,
  STARTER_RECORD_NOTE,
  UNDERCOUNT_DISCLOSURE,
} from '../../lib/playerStats'
import { usePlayerStatsCredit } from '../usePlayerStatsCredit'
import type { LeadersView } from './leadersSearch'
import { parseLeadersSearch, toLeadersSearch } from './leadersSearch'
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
 * NFL career leaders (issue #296): who threw for the most, threw the most
 * touchdowns, or won the most as a starter, in the regular season or the
 * playoffs. The API sorts, ranks and pages; this page renders what it sends
 * and keeps season type, sort and offset in the URL, so a shared link, a
 * reload and the Back button all show the same table.
 *
 * Pages own composition/data-fetching; components do not import from pages
 * (enforced by dependency-cruiser -- see .dependency-cruiser.cjs).
 */
export function PlayerLeadersPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const view = parseLeadersSearch(searchParams)
  const { season_type: seasonType, sort, offset } = view
  const key = toLeadersSearch(view).toString()
  const [answer, setAnswer] = useState<Answer | null>(null)
  const credit = usePlayerStatsCredit()
  const noteId = useId()

  useEffect(() => {
    // Every URL change asks again; an answer for a URL since left is dropped.
    let cancelled = false
    const requestKey = toLeadersSearch({
      season_type: seasonType,
      sort,
      offset,
    }).toString()
    fetchPlayerLeaders({
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
  }, [seasonType, sort, offset])

  const pending = answer?.key !== key

  /** Pushes a history entry, so Back returns to the table before. */
  function show(next: LeadersView) {
    setSearchParams(toLeadersSearch(next))
  }

  function handleSort(nextSort: PlayerLeaderSort) {
    if (nextSort !== sort) {
      show({ season_type: seasonType, sort: nextSort, offset: 0 })
    }
  }

  function handleSeasonType(nextSeasonType: PlayerSeasonType) {
    show({ season_type: nextSeasonType, sort, offset: 0 })
  }

  function handlePage(nextOffset: number) {
    show({ season_type: seasonType, sort, offset: nextOffset })
  }

  // The last good table stays up while the next one loads, so a pressed
  // header or pager button keeps its focus.
  const leaders = answer?.status === 'success' ? answer.leaders : null
  const failed = answer?.status === 'error' && !pending ? answer : null

  return (
    <main className={styles.wrap}>
      <h1 className={styles.title}>NFL Leaders</h1>
      <p className={styles.lede}>
        Career passing and rushing totals for every NFL player with stat lines
        in the source. Pick a column to rank by.
      </p>

      <SeasonTypeSwitch value={seasonType} onChange={handleSeasonType} />

      <section className={styles.notes} aria-labelledby={`${noteId}-heading`}>
        <h2 id={`${noteId}-heading`} className={styles.notesHeading}>
          About these numbers
        </h2>
        <p id={noteId}>{STARTER_RECORD_NOTE}</p>
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
            noteId={noteId}
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
  noteId,
  onSort,
  onPage,
}: {
  leaders: PlayerLeadersOut
  busy: boolean
  noteId: string
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
        describedBy={noteId}
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
