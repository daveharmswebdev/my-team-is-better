import { useEffect, useState } from 'react'
import { fetchCredits } from '../lib/api/client'
import type { CreditsDataSourceOut } from '../lib/api/types'
import { PLAYER_STATS_SOURCE_ID } from '../lib/playerStats'

/**
 * The player-stats credit for the NFL player pages (issue #296), picked from
 * `/api/credits` by its id -- never by name or position. `null` while it
 * loads, and if the credits can't be had: the credit is not what the visitor
 * came for, so its failure doesn't take the page down, and `PlayerStatsCredit`
 * then links to the About page's credits instead.
 */
export function usePlayerStatsCredit(): CreditsDataSourceOut | null {
  const [credit, setCredit] = useState<CreditsDataSourceOut | null>(null)

  useEffect(() => {
    let cancelled = false
    fetchCredits()
      .then((credits) => {
        if (!cancelled) {
          setCredit(
            credits.data_sources.find(
              (source) => source.id === PLAYER_STATS_SOURCE_ID,
            ) ?? null,
          )
        }
      })
      .catch(() => {
        // Stays `null`: the fallback link is the visible degraded state.
      })
    return () => {
      cancelled = true
    }
  }, [])

  return credit
}
