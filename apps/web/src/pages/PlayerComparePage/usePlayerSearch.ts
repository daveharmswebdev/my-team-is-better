import { useEffect, useState } from 'react'
import type { PlayerSearchStatus } from '../../components/PlayerCombobox/PlayerCombobox'
import { searchPlayers } from '../../lib/api/client'
import type { PlayerSearchRowOut } from '../../lib/api/types'

/** How long typing must pause before a search is sent. */
export const SEARCH_DEBOUNCE_MS = 250

/** The API's `PLAYER_SEARCH_MIN_QUERY_LENGTH`, counted after stripping. */
const MIN_QUERY_LENGTH = 2

/** The API's `PLAYER_SEARCH_MAX_QUERY_LENGTH`. */
const MAX_QUERY_LENGTH = 100

type Answer =
  | { query: string; status: 'done'; rows: PlayerSearchRowOut[] }
  | { query: string; status: 'error' }

export interface PlayerSearchState {
  status: PlayerSearchStatus
  /** The latest rows; while a new search is in flight, the previous one's. */
  rows: PlayerSearchRowOut[]
}

/**
 * Debounced `GET /api/players/search` for a combobox's typed text (issue
 * #301). Stripped text of 2..100 characters is searched, so there are at
 * least two non-space characters; anything shorter or longer is never sent
 * (the API would 422 it). An answer for text since changed is dropped.
 */
export function usePlayerSearch(text: string): PlayerSearchState {
  const query = text.trim()
  const eligible =
    query.length >= MIN_QUERY_LENGTH && query.length <= MAX_QUERY_LENGTH
  const [answer, setAnswer] = useState<Answer | null>(null)

  useEffect(() => {
    if (!eligible) {
      return
    }
    let cancelled = false
    const timer = setTimeout(() => {
      searchPlayers(query).then(
        (result) => {
          if (!cancelled) {
            setAnswer({ query, status: 'done', rows: result.rows })
          }
        },
        () => {
          if (!cancelled) {
            setAnswer({ query, status: 'error' })
          }
        },
      )
    }, SEARCH_DEBOUNCE_MS)
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [query, eligible])

  if (!eligible) {
    return { status: 'idle', rows: [] }
  }
  if (answer === null || answer.query !== query) {
    return {
      status: 'searching',
      rows: answer?.status === 'done' ? answer.rows : [],
    }
  }
  return answer.status === 'done'
    ? { status: 'done', rows: answer.rows }
    : { status: 'error', rows: [] }
}
