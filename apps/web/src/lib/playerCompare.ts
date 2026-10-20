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
  PlayerStatsOut,
  StarterRecordOut,
} from './api/types'
import { formatRecord } from './formatRecord'
import type {
  LeaderColumnExtras,
  StatGroup,
  TableStatColumn,
} from './playerStats'
import {
  DASH,
  NOT_RECORDED,
  formatStat,
  leaderStatCell,
  recordedStatGroups,
  showsStarterRecord,
  statColumnsFor,
  statValue,
} from './playerStats'

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

export interface ComparisonRow extends LeaderColumnExtras {
  key: string
  label: string
  /**
   * The formatted value -- `NOT_RECORDED` for a stat the source didn't
   * track, `DASH` for one that can't exist (no longest kick) -- or `null`
   * when the player has no totals of this type.
   */
  a: string | null
  b: string | null
  marked: Side | null
}

interface RowSpec extends LeaderColumnExtras {
  key: string
  label: string
  text: (totals: PlayerCareerTotalsOut) => string
  marked: (a: PlayerCareerTotalsOut, b: PlayerCareerTotalsOut) => Side | null
}

const SEASONS_ROW: RowSpec = {
  key: 'seasons',
  label: 'Seasons',
  text: (totals) => formatStat(totals.seasons),
  marked: (a, b) => largerSide(a.seasons, b.seasons),
}

const GAMES_ROW: RowSpec = {
  key: 'games',
  label: 'Games',
  text: (totals) => formatStat(totals.games),
  marked: (a, b) => largerSide(a.games, b.games),
}

const RECORD_ROW: RowSpec = {
  key: 'record',
  label: 'Starter record',
  text: ({ record }) => formatRecord(record.wins, record.losses, record.ties),
  marked: (a, b) => largerRecordSide(a.record, b.record),
}

/** A stat cell as text: the value, `NOT_RECORDED`, or `DASH`. */
function statText(totals: PlayerCareerTotalsOut, key: keyof PlayerStatsOut) {
  const cell = leaderStatCell(totals.stats, key)
  switch (cell.kind) {
    case 'value':
      return cell.text
    case 'not-recorded':
      return NOT_RECORDED
    case 'none':
      return DASH
  }
}

function statRow(column: TableStatColumn): RowSpec {
  return {
    key: column.key,
    label: column.label,
    fullLabel: column.fullLabel,
    note: column.note,
    text: (totals) => statText(totals, column.key),
    marked: (a, b) =>
      largerSide(
        statValue(a.stats, column.key),
        statValue(b.stats, column.key),
      ),
  }
}

/**
 * The comparison's rows, in order (issue #352): seasons, games, the starter
 * record when either player passed or started, then the stat groups either
 * player recorded (`statColumnsFor`). No sack rows until #298.
 */
function rowSpecs(totals: readonly PlayerCareerTotalsOut[]): RowSpec[] {
  return [
    SEASONS_ROW,
    GAMES_ROW,
    ...(showsStarterRecord(totals) ? [RECORD_ROW] : []),
    ...statColumnsFor(totals.map((side) => side.stats)).map(statRow),
  ]
}

/** Both players' totals of one season type, row by row, with each row's mark. */
export function comparisonRows(
  a: PlayerCareerTotalsOut | null,
  b: PlayerCareerTotalsOut | null,
): ComparisonRow[] {
  const present = [a, b].filter(
    (side): side is PlayerCareerTotalsOut => side !== null,
  )
  return rowSpecs(present).map((row) => ({
    key: row.key,
    label: row.label,
    fullLabel: row.fullLabel,
    note: row.note,
    a: a === null ? null : row.text(a),
    b: b === null ? null : row.text(b),
    marked: a === null || b === null ? null : row.marked(a, b),
  }))
}

/** How a head-to-head line names one stat, in the singular and the plural. */
interface LinePart {
  key: keyof PlayerStatsOut
  singular: string
  plural: string
}

/**
 * What a head-to-head line says for each group (issue #352): the passing
 * line as it always was, and a short line for each other group.
 */
const HEAD_TO_HEAD_PARTS: Record<StatGroup, readonly LinePart[]> = {
  passing: [
    { key: 'passing_yards', singular: 'passing yard', plural: 'passing yards' },
    { key: 'passing_tds', singular: 'TD', plural: 'TDs' },
    { key: 'passing_interceptions', singular: 'INT', plural: 'INTs' },
  ],
  rushing: [
    { key: 'carries', singular: 'carry', plural: 'carries' },
    { key: 'rushing_yards', singular: 'rushing yard', plural: 'rushing yards' },
    { key: 'rushing_tds', singular: 'rushing TD', plural: 'rushing TDs' },
  ],
  receiving: [
    { key: 'receptions', singular: 'reception', plural: 'receptions' },
    {
      key: 'receiving_yards',
      singular: 'receiving yard',
      plural: 'receiving yards',
    },
    { key: 'receiving_tds', singular: 'receiving TD', plural: 'receiving TDs' },
  ],
  kicking: [
    { key: 'fg_made', singular: 'field goal made', plural: 'field goals made' },
    { key: 'fg_att', singular: 'field-goal try', plural: 'field-goal tries' },
    {
      key: 'pat_made',
      singular: 'extra point made',
      plural: 'extra points made',
    },
  ],
  punting: [
    { key: 'pt_att', singular: 'punt', plural: 'punts' },
    { key: 'pt_yards', singular: 'punting yard', plural: 'punting yards' },
  ],
  defense: [
    { key: 'def_sacks', singular: 'sack', plural: 'sacks' },
    {
      key: 'def_interceptions',
      singular: 'interception',
      plural: 'interceptions',
    },
    {
      key: 'def_tackles_solo',
      singular: 'solo tackle',
      plural: 'solo tackles',
    },
  ],
}

/** "328 passing yards", "1 TD", "1.5 sacks", or "TDs not recorded". */
function linePart(stats: PlayerStatsOut, part: LinePart): string {
  const value = statValue(stats, part.key)
  if (value === null) {
    return `${part.plural} ${NOT_RECORDED}`
  }
  const cell = leaderStatCell(stats, part.key)
  const text = cell.kind === 'value' ? cell.text : formatStat(value)
  return `${text} ${value === 1 ? part.singular : part.plural}`
}

/**
 * One starter's line in one head-to-head game (issue #352): the groups he
 * recorded in that game, by the career table's rule (`recordedStatGroups`),
 * a group's stats joined by commas and the groups by semicolons. No stat
 * line at all is "not recorded".
 */
export function headToHeadStatLine(
  name: string,
  stats: PlayerStatsOut | null,
): string {
  if (stats === null) {
    return `${name}: ${NOT_RECORDED}`
  }
  const groups = recordedStatGroups([stats]).map((group) =>
    HEAD_TO_HEAD_PARTS[group].map((part) => linePart(stats, part)).join(', '),
  )
  return `${name}: ${groups.join('; ')}`
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
