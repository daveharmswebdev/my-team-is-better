import { useEffect, useId, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { PlayerCareerTable } from '../../components/PlayerCareerTable/PlayerCareerTable'
import { PlayerStatsCredit } from '../../components/PlayerStatsCredit/PlayerStatsCredit'
import {
  PlayerApiError,
  SERVER_ERROR_COPY,
  VerdictHttpError,
  VerdictNetworkError,
  fetchPlayerCareer,
} from '../../lib/api/client'
import type {
  PlayerCareerOut,
  PlayerCareerTotalsOut,
  PlayerSeasonType,
} from '../../lib/api/types'
import {
  PLAYER_NOT_FOUND_COPY,
  SEASON_TYPE_LABEL,
  STARTER_RECORD_NOTE,
} from '../../lib/playerStats'
import { usePlayerStatsCredit } from '../usePlayerStatsCredit'
import styles from './PlayerCareerPage.module.css'

/** The latest answer, tagged with the player id it answers. */
type Answer =
  | { id: number; status: 'success'; career: PlayerCareerOut }
  | { id: number; status: 'not_found' }
  | { id: number; status: 'error'; message: string }

/**
 * The route's `:playerId` as an id the API could hold, or `null`. Anything
 * else (`kurt-warner`, `-1`, `1.5`) can't name a player, so it is a not-found
 * without a request, rather than a 422 answered with the garbled-question line.
 */
function parsePlayerId(raw: string | undefined): number | null {
  if (raw === undefined || !/^\d+$/.test(raw)) {
    return null
  }
  const id = Number(raw)
  return Number.isSafeInteger(id) ? id : null
}

/** What the "no games of this type" line says. */
const NO_GAMES: Record<PlayerSeasonType, string> = {
  regular: 'No regular-season games on record.',
  postseason: 'No playoff games on record.',
}

/**
 * One NFL player's career (issue #296): every season line the API sent,
 * regular season and playoffs in their own tables, each with the API's
 * career totals. Nothing is summed, sorted or rated here.
 *
 * Pages own composition/data-fetching; components do not import from pages
 * (enforced by dependency-cruiser -- see .dependency-cruiser.cjs).
 */
export function PlayerCareerPage() {
  const { playerId } = useParams()
  const id = parsePlayerId(playerId)
  const [answer, setAnswer] = useState<Answer | null>(null)
  const credit = usePlayerStatsCredit()
  const noteId = useId()

  useEffect(() => {
    if (id === null) {
      return
    }
    let cancelled = false
    fetchPlayerCareer(id)
      .then((career) => {
        if (!cancelled) {
          setAnswer({ id, status: 'success', career })
        }
      })
      .catch((error: unknown) => {
        if (cancelled) {
          return
        }
        if (error instanceof PlayerApiError) {
          setAnswer({ id, status: 'not_found' })
          return
        }
        // Both carry plain narrator copy, never a raw status (issue #215).
        const message =
          error instanceof VerdictNetworkError ||
          error instanceof VerdictHttpError
            ? error.message
            : SERVER_ERROR_COPY
        setAnswer({ id, status: 'error', message })
      })
    return () => {
      cancelled = true
    }
  }, [id])

  const current = id !== null && answer?.id === id ? answer : null
  const notFound = id === null || current?.status === 'not_found'

  return (
    <main className={styles.wrap}>
      <p className={styles.back}>
        <Link to="/nfl/leaders">
          <span aria-hidden="true">&larr; </span>NFL leaders
        </Link>
      </p>

      {current?.status === 'success' ? (
        <Career career={current.career} noteId={noteId} />
      ) : (
        <>
          <h1 className={styles.title}>NFL player</h1>
          {notFound ? (
            <div role="alert" className={styles.error}>
              <p>
                {PLAYER_NOT_FOUND_COPY}{' '}
                <Link to="/nfl/leaders">Pick one off the leaders board.</Link>
              </p>
            </div>
          ) : current?.status === 'error' ? (
            <p role="alert" className={styles.error}>
              {current.message}
            </p>
          ) : (
            <p role="status" className={styles.status}>
              Loading the player&hellip;
            </p>
          )}
        </>
      )}

      <PlayerStatsCredit credit={credit} />
    </main>
  )
}

function Career({
  career,
  noteId,
}: {
  career: PlayerCareerOut
  noteId: string
}) {
  const sections: [PlayerSeasonType, PlayerCareerTotalsOut | null][] = [
    ['regular', career.regular_season],
    ['postseason', career.postseason],
  ]
  return (
    <>
      <header className={styles.header}>
        <h1 className={styles.title}>{career.display_name}</h1>
        <p className={styles.position}>
          {career.position ?? 'Position not recorded'}
        </p>
      </header>

      <p className={styles.compare}>
        <Link to={`/nfl/compare?a=${career.player_id}`}>
          Compare {career.display_name} with another player
        </Link>
      </p>

      <p id={noteId} className={styles.note}>
        {STARTER_RECORD_NOTE}
      </p>

      {sections.map(([seasonType, totals]) => {
        // Kept in the API's order: filtering by season type, not sorting.
        const lines = career.seasons.filter(
          (line) => line.season_type === seasonType,
        )
        const label = SEASON_TYPE_LABEL[seasonType]
        const headingId = `${noteId}-${seasonType}`
        return (
          <section
            key={seasonType}
            className={styles.section}
            aria-labelledby={headingId}
          >
            <h2 id={headingId} className={styles.heading}>
              {label}
            </h2>
            {lines.length === 0 ? (
              <p className={styles.none}>{NO_GAMES[seasonType]}</p>
            ) : (
              <PlayerCareerTable
                caption={`${career.display_name}, ${label.toLowerCase()}`}
                lines={lines}
                totals={totals}
                describedBy={noteId}
              />
            )}
          </section>
        )
      })}
    </>
  )
}
