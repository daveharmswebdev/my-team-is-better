/**
 * Display rules and copy for the NFL player pages (issue #296). Everything
 * here formats what the API sent; nothing sorts, ranks, totals or derives a
 * rate from it -- with one deliberate, narrow exception (issue #315).
 *
 * The exception: the kicking board's FG% and 50+ columns. The engine ranks
 * by both but sends neither (they are computed sorts, not stats), so the
 * board derives each row's value from the counts it was sent:
 * `fg_made / fg_att` and `fg_made_50_59 + fg_made_60_`. Both live in
 * `deriveKickingStats` and nowhere else. Nothing here re-ranks or re-sorts
 * by them -- the order and the ranks stay the API's -- and no other rate
 * (PAT%, yards per punt) is derived.
 */
import type {
  PlayerLeaderCategory,
  PlayerLeaderSort,
  PlayerSeasonType,
  PlayerStatsOut,
} from './api/types'
import {
  PLAYER_LEADER_FG_PCT_MIN_ATTEMPTS,
  PLAYER_LEADER_SORTS_BY_CATEGORY,
} from './api/types'

/** What a stat the source didn't track reads as: never 0, never blank. */
export const NOT_RECORDED = 'not recorded'

/**
 * What a value that cannot exist shows (issue #315): the longest field goal
 * of a kicker who never made one, or the FG% of one who never tried. Not 0,
 * which would claim a zero-yard kick, and not `NOT_RECORDED`, since nothing
 * went untracked. Shown, hidden from assistive tech, beside `NONE_LABEL`.
 */
export const DASH = '–'

/** How assistive tech reads a `DASH` cell. */
export const NONE_LABEL = 'none'

/** A stat as sent, with thousands grouped and its sign kept; `null` is `NOT_RECORDED`. */
export function formatStat(value: number | null): string {
  return value === null ? NOT_RECORDED : value.toLocaleString('en-US')
}

export interface StatColumn {
  key: keyof PlayerStatsOut
  label: string
}

/**
 * The two kicking sorts the engine computes and does not send (issue #315).
 * Each names both a sort and the leaderboard column that shows it.
 */
export type DerivedKickingStat = Extract<
  PlayerLeaderSort,
  'fg_pct' | 'fg_made_50_plus'
>

/** A leaderboard column whose value `deriveKickingStats` computes. */
export interface DerivedStatColumn {
  key: DerivedKickingStat
  label: string
}

/** What a leaderboard column shows: a stat as sent, or one of the two derived ones. */
export type LeaderStatKey = keyof PlayerStatsOut | DerivedKickingStat

/** A leaderboard column. The career and compare tables only ever take a `StatColumn`. */
export type LeaderStatColumn = StatColumn | DerivedStatColumn

export interface DerivedKickingStats {
  /** `fg_made / fg_att`, unrounded; `null` with no attempts or a null count. */
  fg_pct: number | null
  /** `fg_made_50_59 + fg_made_60_`; `null` when either is null. */
  fg_made_50_plus: number | null
}

/**
 * The only derivation in apps/web (issue #315; see this file's header). The
 * engine ranks the kicking board by these two but does not send them, so a
 * row's FG% and 50+ are computed here from the counts that row carries --
 * the same formulas the engine ranks by.
 */
export function deriveKickingStats(
  stats: Pick<
    PlayerStatsOut,
    'fg_made' | 'fg_att' | 'fg_made_50_59' | 'fg_made_60_'
  >,
): DerivedKickingStats {
  const { fg_made: made, fg_att: attempts } = stats
  const { fg_made_50_59: fifties, fg_made_60_: sixties } = stats
  return {
    fg_pct:
      made === null || attempts === null || attempts === 0
        ? null
        : made / attempts,
    fg_made_50_plus:
      fifties === null || sixties === null ? null : fifties + sixties,
  }
}

/**
 * The career maxima (the engine's `PLAYER_STAT_MAX_FIELDS`): `null` means he
 * never made a field goal or never punted, so it reads `DASH`, not
 * `NOT_RECORDED`.
 */
const MAX_STATS: ReadonlySet<keyof PlayerStatsOut> = new Set([
  'fg_long',
  'pt_long',
])

/** One leaderboard stat cell: a value, "not recorded", or a `DASH` read as `NONE_LABEL`. */
export type LeaderCell =
  { kind: 'value'; text: string } | { kind: 'not-recorded' } | { kind: 'none' }

function valueCell(value: number | null): LeaderCell {
  return value === null
    ? { kind: 'not-recorded' }
    : { kind: 'value', text: formatStat(value) }
}

/** FG% to one decimal with a percent sign: "94.7%". */
function formatFgPct(ratio: number): string {
  return `${(ratio * 100).toFixed(1)}%`
}

/** What a leaderboard shows under a column, for one row's stats. */
export function leaderStatCell(
  stats: PlayerStatsOut,
  key: LeaderStatKey,
): LeaderCell {
  if (key === 'fg_pct') {
    const { fg_pct: ratio } = deriveKickingStats(stats)
    return ratio === null
      ? { kind: 'none' }
      : { kind: 'value', text: formatFgPct(ratio) }
  }
  if (key === 'fg_made_50_plus') {
    return valueCell(deriveKickingStats(stats).fg_made_50_plus)
  }
  const value = stats[key]
  if (value === null && MAX_STATS.has(key)) {
    return { kind: 'none' }
  }
  return valueCell(value)
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
  receiving_yards: 'receiving yards',
  receiving_tds: 'receiving TDs',
  receptions: 'receptions',
  fg_made: 'field goals made',
  fg_pct: 'field-goal percentage',
  fg_made_50_plus: 'field goals from 50+',
  fg_long: 'longest field goal',
  fg_att: 'field-goal attempts',
  pat_made: 'extra points made',
  pt_yards: 'punting yards',
  pt_net_yards: 'net punting yards',
  pt_att: 'punts',
  pt_inside_20: 'punts inside the 20',
}

/** How the category dropdown names each board (issues #312, #314, #315). */
export const CATEGORY_LABEL: Record<PlayerLeaderCategory, string> = {
  passing: 'Passing',
  rushing: 'Rushing',
  receiving: 'Receiving',
  kicking: 'Kicking',
  punting: 'Punting',
}

/** The stat keys the rushing board shows; their labels and order come from `STAT_COLUMNS`. */
const RUSHING_STAT_KEYS: readonly (keyof PlayerStatsOut)[] = [
  'carries',
  'rushing_yards',
  'rushing_tds',
]

/**
 * The receiving board's columns (issue #314), the rushing board's shape.
 * Deliberately its own list and not part of `STAT_COLUMNS`: the career and
 * compare tables read `STAT_COLUMNS`, and non-QB career and compare pages are
 * outside epic #311, so those tables show exactly what they did. `targets` is
 * left out everywhere: the source publishes it as 0 for 2003-2008 (#345), so
 * a career total spanning those years undercounts. First downs and fumbles
 * lost are mirrored in the type but not shown in v1.
 */
const RECEIVING_COLUMNS: readonly StatColumn[] = [
  { key: 'receptions', label: 'Receptions' },
  { key: 'receiving_yards', label: 'Receiving yards' },
  { key: 'receiving_tds', label: 'Receiving TDs' },
]

/**
 * The kicking board's columns (issue #315). FG% and 50+ are the two derived
 * ones (`deriveKickingStats`); each carries its own sort as its key, like
 * every other column. `pat_att` is mirrored but not shown, and the 50-59 and
 * 60+ buckets show only summed.
 */
const KICKING_COLUMNS: readonly LeaderStatColumn[] = [
  { key: 'fg_made', label: 'FG made' },
  { key: 'fg_att', label: 'FG att' },
  { key: 'fg_pct', label: 'FG%' },
  { key: 'fg_made_50_plus', label: '50+' },
  { key: 'fg_long', label: 'Long' },
  { key: 'pat_made', label: 'XP made' },
]

/** The punting board's columns (issue #315). `pt_long` is mirrored but not shown. */
const PUNTING_COLUMNS: readonly StatColumn[] = [
  { key: 'pt_att', label: 'Punts' },
  { key: 'pt_yards', label: 'Yards' },
  { key: 'pt_net_yards', label: 'Net yards' },
  { key: 'pt_inside_20', label: 'Inside 20' },
]

export interface LeaderBoardColumns {
  /**
   * Whether this board shows the starter record and starts -- and so whether
   * `STARTER_RECORD_NOTE` has anything to explain on it. Only the passing
   * board does: the other boards' rows are mostly 0-0-0 non-quarterbacks.
   */
  showsRecord: boolean
  /** The stat columns, in order. */
  stats: readonly LeaderStatColumn[]
}

/**
 * What each leaderboard shows (issue #312), stated once. Which of these
 * columns re-sorts the board is not repeated here: it follows from the
 * category's own sorts -- see `sortForStat`. Checked with `satisfies` rather
 * than annotated, so the boards with no derived column keep their narrower
 * `StatColumn` type.
 */
export const LEADER_BOARD_COLUMNS = {
  passing: { showsRecord: true, stats: STAT_COLUMNS },
  rushing: {
    showsRecord: false,
    stats: STAT_COLUMNS.filter((column) =>
      RUSHING_STAT_KEYS.includes(column.key),
    ),
  },
  receiving: { showsRecord: false, stats: RECEIVING_COLUMNS },
  kicking: { showsRecord: false, stats: KICKING_COLUMNS },
  punting: { showsRecord: false, stats: PUNTING_COLUMNS },
} satisfies Record<PlayerLeaderCategory, LeaderBoardColumns>

/** One category's board, at the common column type. */
export function leaderBoardColumns(
  category: PlayerLeaderCategory,
): LeaderBoardColumns {
  return LEADER_BOARD_COLUMNS[category]
}

/**
 * The sort a stat column re-sorts the board by, or `undefined` when this
 * category doesn't sort on it. Read straight off the category's sort list,
 * so a category gaining a sort makes its column sortable with no change
 * here. A derived column's key is its own sort (`fg_pct`,
 * `fg_made_50_plus`), so it is matched the same way.
 */
export function sortForStat(
  category: PlayerLeaderCategory,
  key: LeaderStatKey,
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

/**
 * The note on the FG% board (issue #315): it is the one sort with an
 * attempts minimum, which is why it can be short, or empty. The number is
 * the mirrored engine constant's, never restated.
 */
export function fgPctNote(seasonType: PlayerSeasonType): string {
  const minimum = String(PLAYER_LEADER_FG_PCT_MIN_ATTEMPTS[seasonType])
  const span = SEASON_TYPE_LABEL[seasonType].toLowerCase()
  return `Field-goal percentage ranks only kickers with at least ${minimum} career field-goal attempts in the ${span}. Every other kicking column ranks every player with a field-goal or extra-point attempt.`
}

/** What an empty FG% board says: nobody reached the minimum, not that no stats are loaded. */
export function fgPctEmptyCopy(seasonType: PlayerSeasonType): string {
  const minimum = String(PLAYER_LEADER_FG_PCT_MIN_ATTEMPTS[seasonType])
  const span = SEASON_TYPE_LABEL[seasonType].toLowerCase()
  return `No kicker has reached ${minimum} career field-goal attempts in the ${span}, so nobody qualifies for the field-goal percentage board.`
}

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
