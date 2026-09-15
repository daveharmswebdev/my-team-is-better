/**
 * Display rules and copy for the NFL player pages (issue #296). Everything
 * here formats what the API sent; nothing sorts, ranks, totals or derives a
 * rate from it.
 */
import type {
  PlayerLeaderCategory,
  PlayerLeaderSort,
  PlayerSeasonType,
  PlayerStatsOut,
} from './api/types'
import { PLAYER_LEADER_SORTS_BY_CATEGORY } from './api/types'

/** What a stat the source didn't track reads as: never 0, never blank. */
export const NOT_RECORDED = 'not recorded'

/** A stat as sent, with thousands grouped and its sign kept; `null` is `NOT_RECORDED`. */
export function formatStat(value: number | null): string {
  return value === null ? NOT_RECORDED : value.toLocaleString('en-US')
}

export interface StatColumn {
  key: keyof PlayerStatsOut
  label: string
}

/**
 * The stat columns both player tables show, in order. Deliberately without
 * `sacks_suffered` and `sack_yards_lost`: the stored sack yards are negative
 * against the column's name (#298), so neither is shown in v1.
 */
export const STAT_COLUMNS: readonly StatColumn[] = [
  { key: 'completions', label: 'Completions' },
  { key: 'attempts', label: 'Attempts' },
  { key: 'passing_yards', label: 'Passing yards' },
  { key: 'passing_tds', label: 'Passing TDs' },
  { key: 'passing_interceptions', label: 'Interceptions' },
  { key: 'carries', label: 'Carries' },
  { key: 'rushing_yards', label: 'Rushing yards' },
  { key: 'rushing_tds', label: 'Rushing TDs' },
]

export const SEASON_TYPE_LABEL: Record<PlayerSeasonType, string> = {
  regular: 'Regular season',
  postseason: 'Playoffs',
}

/** How a caption names each sort ("by passing yards"). */
export const SORT_LABEL: Record<PlayerLeaderSort, string> = {
  passing_yards: 'passing yards',
  passing_tds: 'passing TDs',
  wins: 'starter wins',
  rushing_yards: 'rushing yards',
  rushing_tds: 'rushing TDs',
  carries: 'carries',
}

/** How the category dropdown names each board (issue #312). */
export const CATEGORY_LABEL: Record<PlayerLeaderCategory, string> = {
  passing: 'Passing',
  rushing: 'Rushing',
}

/** The stat keys the rushing board shows; their labels and order come from `STAT_COLUMNS`. */
const RUSHING_STAT_KEYS: readonly (keyof PlayerStatsOut)[] = [
  'carries',
  'rushing_yards',
  'rushing_tds',
]

export interface LeaderBoardColumns {
  /**
   * Whether this board shows the starter record and starts -- and so whether
   * `STARTER_RECORD_NOTE` has anything to explain on it. Only the passing
   * board does: a rushing board's rows are mostly 0-0-0 non-quarterbacks.
   */
  showsRecord: boolean
  /** The stat columns, in order. */
  stats: readonly StatColumn[]
}

/**
 * What each leaderboard shows (issue #312), stated once. Which of these
 * columns re-sorts the board is not repeated here: it follows from the
 * category's own sorts -- see `sortForStat`.
 */
export const LEADER_BOARD_COLUMNS: Record<
  PlayerLeaderCategory,
  LeaderBoardColumns
> = {
  passing: { showsRecord: true, stats: STAT_COLUMNS },
  rushing: {
    showsRecord: false,
    stats: STAT_COLUMNS.filter((column) =>
      RUSHING_STAT_KEYS.includes(column.key),
    ),
  },
}

/**
 * The sort a stat column re-sorts the board by, or `undefined` when this
 * category doesn't sort on it. Read straight off the category's sort list,
 * so a category gaining a sort makes its column sortable with no change
 * here.
 */
export function sortForStat(
  category: PlayerLeaderCategory,
  key: keyof PlayerStatsOut,
): PlayerLeaderSort | undefined {
  const sorts: readonly PlayerLeaderSort[] =
    PLAYER_LEADER_SORTS_BY_CATEGORY[category]
  return sorts.find((sort) => sort === key)
}

/** One season, or a first–last span. */
export function formatSeasonSpan(first: number, last: number): string {
  return first === last ? String(first) : `${first}–${last}`
}

/** The `id` of the player-stats credit in `/api/credits` `data_sources`. */
export const PLAYER_STATS_SOURCE_ID = 'nflverse_player_stats'

/**
 * Founder decision (#288/#289): the source's listed starter stands. When a QB
 * leaves early and the source lists his replacement, the game goes on the
 * replacement's record, so the pulled starter shows one decision fewer than
 * the official record: 2004_17_IND_DEN lists Jim Sorgi (Manning threw 2
 * passes), which is why Manning 2004 reads 12-3 against the official 12-4.
 * Stated once per page, next to the tables that show records.
 */
export const STARTER_RECORD_NOTE =
  "Starter records follow the source's listed starter. When a quarterback left a game early and the source lists the replacement as the starter, that game counts toward the replacement, so a record here can show fewer decisions than the official one (Peyton Manning's 2004 reads 12-3 here, 12-4 officially)."

/** The leaders page's note on games the source has no stat lines for (#288/#289). */
export const UNDERCOUNT_DISCLOSURE =
  "Totals only count games the source has stat lines for. A player's page flags each season with games missing from the source."

/** What "not recorded" means, on the leaders page. */
export const NOT_RECORDED_DISCLOSURE =
  "“Not recorded” means the source didn't track that stat, which isn't the same as zero."

/** The disclosure on a season line with `games_without_stat_lines > 0`. */
export function undercountNote(games: number): string {
  return games === 1
    ? 'Totals undercount 1 game: the source has no stat lines for it.'
    : `Totals undercount ${games} games: the source has no stat lines for them.`
}

/** The narrator's line for an `unknown_player` 404, or a player id that can't be one. */
export const PLAYER_NOT_FOUND_COPY =
  "Never heard of him, pal. There's no NFL player by that number in my book."
