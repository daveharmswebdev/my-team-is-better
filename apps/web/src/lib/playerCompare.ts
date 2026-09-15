/**
 * Display rules and copy for the NFL player comparison (issue #301). Like
 * `playerStats.ts`, everything here formats what the API sent. The one rule
 * it adds is the founder's marking rule (#301): in each row, mark the larger
 * number, and nothing more. No tally, no overall winner, no per-game or rate
 * stat, and no copy that reads a mark as a lead or as better.
 */
import type {
  PlayerCareerOut,
  PlayerCareerTotalsOut,
  PlayerHeadToHeadGameOut,
  PlayerSeasonType,
  StarterRecordOut,
} from './api/types'
import { formatRecord } from './formatRecord'
import { STAT_COLUMNS, formatStat } from './playerStats'

/** Player A's side of a comparison, or player B's. */
export type Side = 'a' | 'b'

/**
 * The side holding the larger number, or `null` when the two are equal or
 * either wasn't recorded. Larger, not better: more interceptions is marked too.
 */
export function largerSide(a: number | null, b: number | null): Side | null {
  if (a === null || b === null || a === b) {
    return null
  }
  return a > b ? 'a' : 'b'
}

/** A starter-record row compares wins, and only wins. */
export function largerRecordSide(
  a: StarterRecordOut,
  b: StarterRecordOut,
): Side | null {
  return largerSide(a.wins, b.wins)
}

export interface ComparisonRow {
  key: string
  label: string
  /** The formatted value, or `null` when the player has no totals of this type. */
  a: string | null
  b: string | null
  marked: Side | null
}

interface RowSpec {
  key: string
  label: string
  text: (totals: PlayerCareerTotalsOut) => string
  marked: (a: PlayerCareerTotalsOut, b: PlayerCareerTotalsOut) => Side | null
}

/** The comparison's rows, in order. No sack rows until #298. */
const ROWS: readonly RowSpec[] = [
  {
    key: 'seasons',
    label: 'Seasons',
    text: (totals) => formatStat(totals.seasons),
    marked: (a, b) => largerSide(a.seasons, b.seasons),
  },
  {
    key: 'games',
    label: 'Games',
    text: (totals) => formatStat(totals.games),
    marked: (a, b) => largerSide(a.games, b.games),
  },
  {
    key: 'record',
    label: 'Starter record',
    text: ({ record }) => formatRecord(record.wins, record.losses, record.ties),
    marked: (a, b) => largerRecordSide(a.record, b.record),
  },
  ...STAT_COLUMNS.map((column): RowSpec => ({
    key: column.key,
    label: column.label,
    text: (totals) => formatStat(totals.stats[column.key]),
    marked: (a, b) => largerSide(a.stats[column.key], b.stats[column.key]),
  })),
]

/** Both players' totals of one season type, row by row, with each row's mark. */
export function comparisonRows(
  a: PlayerCareerTotalsOut | null,
  b: PlayerCareerTotalsOut | null,
): ComparisonRow[] {
  return ROWS.map((row) => ({
    key: row.key,
    label: row.label,
    a: a === null ? null : row.text(a),
    b: b === null ? null : row.text(b),
    marked: a === null || b === null ? null : row.marked(a, b),
  }))
}

/** The visible mark. Decorative: `MARK_SCREEN_READER_TEXT` says the same in words. */
export const MARK_GLYPH = '▲'

/** What a screen reader hears after a marked number. */
export const MARK_SCREEN_READER_TEXT = '(larger number)'

export const MARK_LEGEND =
  "The marked number in each row is the larger one. Larger isn't the same as better: more interceptions get the mark too."

/** Which games count as head-to-head, verified against the data (#301). */
export const HEAD_TO_HEAD_RULE =
  "Only games both players started at quarterback, for opposite teams, count here. When a starter left early and the source lists the replacement as the starter, the game counts for the replacement: the source lists Jim Sorgi, not Peyton Manning, as the Colts' starter in week 17 of 2004, so that game isn't Manning against Jake Plummer."

export const PICK_TWO_COPY =
  'Pick two players to put their careers side by side.'

/**
 * Under the Compare button while a field holds typed text that isn't a player
 * picked from the list (issue #304). Plain, not the narrator: it's an instruction.
 */
export const PICK_FROM_LIST_COPY =
  'Pick each player from the list, then press Compare.'

export function pickOneMoreCopy(name: string | null): string {
  return name === null
    ? 'Now pick the other player.'
    : `Now pick a player to put next to ${name}.`
}

export const SAME_PLAYER_COPY =
  "That's the same player twice, pal. Nobody goes up against themselves. Pick somebody else for one side."

export const SEARCH_FAILED_COPY =
  "Can't look anybody up right now, pal. Give it a second and type again."

/** One player has no totals of this type. */
export const NO_TOTALS_COPY: Record<PlayerSeasonType, string> = {
  regular: 'No regular-season games on record.',
  postseason: 'No playoff games on record.',
}

/** Neither player has totals of this type. */
export const NEITHER_TOTALS_COPY: Record<PlayerSeasonType, string> = {
  regular: 'Neither player has regular-season games on record.',
  postseason: 'Neither player has playoff games on record.',
}

/** How the head-to-head list of each type is named. */
export const GAMES_LIST_LABEL: Record<PlayerSeasonType, string> = {
  regular: 'Regular-season games',
  postseason: 'Playoff games',
}

/** A season type inside a sentence. */
const SEASON_TYPE_PHRASE: Record<PlayerSeasonType, string> = {
  regular: 'regular season',
  postseason: 'playoffs',
}

export function neverMetCopy(
  aName: string,
  bName: string,
  seasonType: PlayerSeasonType,
): string {
  return `${aName} and ${bName} never started against each other in the ${SEASON_TYPE_PHRASE[seasonType]}.`
}

/** `a`'s record against `b`, naming both. */
export function headToHeadRecordCopy(
  aName: string,
  bName: string,
  record: StarterRecordOut,
): string {
  return `${aName}'s record against ${bName}: ${formatRecord(record.wins, record.losses, record.ties)}`
}

const MONTHS = [
  'Jan',
  'Feb',
  'Mar',
  'Apr',
  'May',
  'Jun',
  'Jul',
  'Aug',
  'Sep',
  'Oct',
  'Nov',
  'Dec',
]

/**
 * An ISO `YYYY-MM-DD` as "Oct 31, 1999", read as a calendar date (no `Date`,
 * so no time zone can move it a day). Anything else is passed through as sent.
 */
export function formatGameDate(isoDate: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(isoDate)
  const month = match === null ? undefined : MONTHS[Number(match[2]) - 1]
  if (match === null || month === undefined) {
    return isoDate
  }
  return `${month} ${Number(match[3])}, ${match[1]}`
}

/** "1999 season · week 8 · Oct 31, 1999", leaving out whatever wasn't sent. */
export function formatGameWhen(game: PlayerHeadToHeadGameOut): string {
  const parts = [`${game.season} season`]
  if (game.week !== null) {
    parts.push(`week ${game.week}`)
  }
  if (game.start_date !== null) {
    parts.push(formatGameDate(game.start_date))
  }
  return parts.join(' · ')
}

/**
 * The career page's undercount disclosure, for both players at once: every
 * season line with games the source has no stat lines for, or `null`.
 */
export function compareUndercountNote(
  a: PlayerCareerOut,
  b: PlayerCareerOut,
): string | null {
  const lines = [a, b].flatMap((career) =>
    career.seasons
      .filter((line) => line.games_without_stat_lines > 0)
      .map((line) => {
        const games = line.games_without_stat_lines
        return `${career.display_name}, ${line.season} ${SEASON_TYPE_PHRASE[line.season_type]}: ${games} ${games === 1 ? 'game' : 'games'}.`
      }),
  )
  if (lines.length === 0) {
    return null
  }
  return [
    'These totals undercount games the source has no stat lines for.',
    ...lines,
  ].join(' ')
}
