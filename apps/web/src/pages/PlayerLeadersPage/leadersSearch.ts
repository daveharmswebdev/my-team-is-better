/**
 * The leaders page's URL state (issue #296, extended by #312): stat category,
 * season type, sort and offset live in the query string, so a link, a reload
 * or the Back button shows the same table. Values the API would refuse fall
 * back to its defaults rather than being sent.
 *
 * `category` is written first, ahead of the `season_type=...&sort=...&offset=...`
 * tail every pre-#312 link already had, and a URL without one is the passing
 * board -- so no existing leaders link changes meaning.
 */
import type {
  PlayerLeaderCategory,
  PlayerLeaderSort,
  PlayerSeasonType,
} from '../../lib/api/types'
import {
  defaultSortFor,
  isPlayerLeaderCategory,
  isPlayerSeasonType,
  isSortInCategory,
} from '../../lib/api/types'

export interface LeadersView {
  category: PlayerLeaderCategory
  season_type: PlayerSeasonType
  sort: PlayerLeaderSort
  offset: number
}

export const DEFAULT_LEADERS_VIEW: LeadersView = {
  category: 'passing',
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
  const rawCategory = params.get('category')
  const category = isPlayerLeaderCategory(rawCategory)
    ? rawCategory
    : DEFAULT_LEADERS_VIEW.category
  const seasonType = params.get('season_type')
  const sort = params.get('sort')
  return {
    category,
    season_type: isPlayerSeasonType(seasonType)
      ? seasonType
      : DEFAULT_LEADERS_VIEW.season_type,
    // A sort belongs to exactly one category, and the API 422s a pair from
    // two. A sort this category doesn't own -- including a valid sort from
    // the other one -- therefore falls back to this category's default.
    sort: isSortInCategory(category, sort) ? sort : defaultSortFor(category),
    offset: parseOffset(params.get('offset')),
  }
}

export function toLeadersSearch(view: LeadersView): URLSearchParams {
  return new URLSearchParams({
    category: view.category,
    season_type: view.season_type,
    sort: view.sort,
    offset: String(view.offset),
  })
}

/**
 * The view a category change lands on: the same season type, that category's
 * default sort (the old one belongs to the old category) and the top of the
 * list, since the boards have different populations.
 */
export function withCategory(
  view: LeadersView,
  category: PlayerLeaderCategory,
): LeadersView {
  return {
    category,
    season_type: view.season_type,
    sort: defaultSortFor(category),
    offset: 0,
  }
}
