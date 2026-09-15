/**
 * The leaders page's URL state (issue #296): season type, sort and offset
 * live in the query string, so a link, a reload or the Back button shows the
 * same table. Values the API would refuse fall back to its defaults rather
 * than being sent.
 */
import type { PlayerLeaderSort, PlayerSeasonType } from '../../lib/api/types'
import { isPlayerLeaderSort, isPlayerSeasonType } from '../../lib/api/types'

export interface LeadersView {
  season_type: PlayerSeasonType
  sort: PlayerLeaderSort
  offset: number
}

export const DEFAULT_LEADERS_VIEW: LeadersView = {
  season_type: 'regular',
  sort: 'passing_yards',
  offset: 0,
}

function parseOffset(raw: string | null): number {
  if (raw === null || !/^\d+$/.test(raw)) {
    return DEFAULT_LEADERS_VIEW.offset
  }
  const offset = Number(raw)
  return Number.isSafeInteger(offset) ? offset : DEFAULT_LEADERS_VIEW.offset
}

export function parseLeadersSearch(params: URLSearchParams): LeadersView {
  const seasonType = params.get('season_type')
  const sort = params.get('sort')
  return {
    season_type: isPlayerSeasonType(seasonType)
      ? seasonType
      : DEFAULT_LEADERS_VIEW.season_type,
    sort: isPlayerLeaderSort(sort) ? sort : DEFAULT_LEADERS_VIEW.sort,
    offset: parseOffset(params.get('offset')),
  }
}

export function toLeadersSearch(view: LeadersView): URLSearchParams {
  return new URLSearchParams({
    season_type: view.season_type,
    sort: view.sort,
    offset: String(view.offset),
  })
}
