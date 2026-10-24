import { useEffect, useState } from 'react'
import type { PlayerSearchStatus } from '../../components/PlayerCombobox/PlayerCombobox'
import { searchPlayers } from '../../lib/api/client'
import type {
  PlayerPositionGroup,
  PlayerSearchRowOut,
} from '../../lib/api/types'

/** How long typing must pause before a search is sent. */
export const SEARCH_DEBOUNCE_MS = 250

/** The API's `PLAYER_SEARCH_MIN_QUERY_LENGTH`, counted after stripping. */
const MIN_QUERY_LENGTH = 2

/** The API's `PLAYER_SEARCH_MAX_QUERY_LENGTH`. */
const MAX_QUERY_LENGTH = 100

/** What a search asked: the stripped text, within a group or not. */
type Asked = string

type Answer =
  | { asked: Asked; status: 'done'; rows: PlayerSearchRowOut[] }
  | { asked: Asked; status: 'error' }

export interface PlayerSearchState {
  status: PlayerSearchStatus
  /** The latest rows; while a new search is in flight, the previous one's. */
  rows: PlayerSearchRowOut[]
}

/**
 * Debounced `GET /api/players/search` for a combobox's typed text (issue
 * #301). Stripped text of 2..100 characters is searched, so there are at
 * least two non-space characters; anything shorter or longer is never sent
 * (the API would 422 it). A `group` keeps the search within that position
 * group (issue #436: Player B searches Player A's); without one the search is
 * unfiltered and sends no group at all. An answer for text or a group since
 * changed is dropped.
 */
export function usePlayerSearch(
  text: string,
  group?: PlayerPositionGroup,
): PlayerSearchState {
  const query = text.trim()
  const eligible =
    query.length >= MIN_QUERY_LENGTH && query.length <= MAX_QUERY_LENGTH
  const asked: Asked = `${group ?? ''}:${query}`
  const [answer, setAnswer] = useState<Answer | null>(null)

  useEffect(() => {
    if (!eligible) {
      return
    }
    // `cancelled` drops any answer once the text moves on; `controller` also
    // aborts the request itself, so a burst of typing has at most one search
    // in flight (issue #370). An aborted search's rejection lands after
    // `cancelled` is set, so it never becomes an error.
    let cancelled = false
    const controller = new AbortController()
    const timer = setTimeout(() => {
      const options =
        group === undefined
          ? { signal: controller.signal }
          : { signal: controller.signal, group }
      searchPlayers(query, options).then(
        (result) => {
          if (!cancelled) {
            setAnswer({ asked, status: 'done', rows: result.rows })
          }
        },
        () => {
          if (!cancelled) {
            setAnswer({ asked, status: 'error' })
          }
        },
      )
    }, SEARCH_DEBOUNCE_MS)
    return () => {
      cancelled = true
      clearTimeout(timer)
      controller.abort()
    }
  }, [query, group, asked, eligible])

  if (!eligible) {
    return { status: 'idle', rows: [] }
  }
  if (answer === null || answer.asked !== asked) {
    return {
      status: 'searching',
      rows: answer?.status === 'done' ? answer.rows : [],
    }
  }
  return answer.status === 'done'
    ? { status: 'done', rows: answer.rows }
    : { status: 'error', rows: [] }
}
