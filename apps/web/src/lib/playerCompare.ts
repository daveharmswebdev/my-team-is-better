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
  PlayerComparisonOut,
  PlayerHeadToHeadGameOut,
  PlayerPositionGroup,
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
  STAT_GROUP_COLUMNS,
  formatStat,
  leaderStatCell,
  recordedStatGroups,
  showsStarterRecord,
  statColumnsForPlayers,
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
 * The stat groups each position group is compared on, in order (founder
 * decision on #438): the position decides the rows, and stats outside it
 * are hidden. A quarterback keeps his rushing even when he never ran.
 */
const POSITION_STAT_GROUPS: Record<PlayerPositionGroup, readonly StatGroup[]> =
  {
    QB: ['passing', 'rushing'],
    RB: ['rushing', 'receiving'],
    WR: ['receiving'],
    TE: ['receiving'],
  }

/**
 * The position group both players share, which decides the compare rows
 * (#438), or `null` when their groups differ or either has none. Since #436
 * the page shows only a shared-group pair.
 */
export function comparisonGroup(
  a: PlayerCareerOut,
  b: PlayerCareerOut,
): PlayerPositionGroup | null {
  return a.group !== null && a.group === b.group ? a.group : null
}

/**
 * Whether a compare table shows the starter record: for two quarterbacks
 * only (#438). A pair with no shared group keeps the recorded-stats rule
 * (#352, `showsStarterRecord`).
 */
function showsRecordRow(
  group: PlayerPositionGroup | null,
  lines: readonly { stats: PlayerStatsOut; record: StarterRecordOut }[],
): boolean {
  return group === null ? showsStarterRecord(lines) : group === 'QB'
}

/** Whether the compare page's tables show a starter record, so need its note. */
export function comparisonShowsRecord(
  a: PlayerCareerOut,
  b: PlayerCareerOut,
): boolean {
  return showsRecordRow(comparisonGroup(a, b), [...a.seasons, ...b.seasons])
}

/**
 * The comparison's rows, in order: seasons, games, then by the position
 * group both players share (#438) -- for a quarterback the starter record,
 * passing and rushing; for a back rushing then receiving; for a receiver
 * or tight end receiving. With no shared group (unreachable on the page
 * since #436), the #352 rule: the starter record when either player passed
 * or started, then the stat groups either player recorded, each judged on
 * his own totals (`statColumnsForPlayers`). No sack rows: like the boards,
 * the comparison doesn't show sacks suffered or sack yards lost (#298).
 */
function rowSpecs(
  totals: readonly PlayerCareerTotalsOut[],
  group: PlayerPositionGroup | null,
): RowSpec[] {
  const columns =
    group === null
      ? statColumnsForPlayers(totals.map((side) => [side.stats]))
      : POSITION_STAT_GROUPS[group].flatMap(
          (statGroup) => STAT_GROUP_COLUMNS[statGroup],
        )
  return [
    SEASONS_ROW,
    GAMES_ROW,
    ...(showsRecordRow(group, totals) ? [RECORD_ROW] : []),
    ...columns.map(statRow),
  ]
}

/**
 * Both players' totals of one season type, row by row, with each row's
 * mark. `group` is the position group both share (`comparisonGroup`).
 */
export function comparisonRows(
  a: PlayerCareerTotalsOut | null,
  b: PlayerCareerTotalsOut | null,
  group: PlayerPositionGroup | null,
): ComparisonRow[] {
  const present = [a, b].filter(
    (side): side is PlayerCareerTotalsOut => side !== null,
  )
  return rowSpecs(present, group).map((row) => ({
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

// ---------------------------------------------------------------------------
// Comparing like with like (issue #436, epic #372). Founder decisions: a
// player's group comes from his position label; Player B is searched within
// Player A's group; a mixed link is refused; head-to-head is QB only. The
// copy was decided on #436 (2026-10-24): only its slots are filled here.
// ---------------------------------------------------------------------------

/** How a position reads in a sentence: "a quarterback", "safeties". */
interface PositionNoun {
  article: 'a' | 'an'
  singular: string
  plural: string
}

/** Each group as the decided copy names it. */
const GROUP_NOUNS: Record<PlayerPositionGroup, PositionNoun> = {
  QB: { article: 'a', singular: 'quarterback', plural: 'quarterbacks' },
  RB: { article: 'a', singular: 'running back', plural: 'running backs' },
  WR: { article: 'a', singular: 'receiver', plural: 'receivers' },
  TE: { article: 'a', singular: 'tight end', plural: 'tight ends' },
}

/**
 * Every `players.position` label in the committed raw cache (players.csv,
 * 25 labels, measured for #428). A label outside it reads generically.
 */
export const MEASURED_POSITION_LABELS = [
  'WR',
  'LB',
  'RB',
  'DB',
  'DE',
  'OT',
  'TE',
  'G',
  'DT',
  'CB',
  'QB',
  'C',
  'OLB',
  'K',
  'P',
  'SAF',
  'S',
  'FS',
  'NT',
  'FB',
  'ILB',
  'MLB',
  'LS',
  'OL',
  'DL',
] as const

type MeasuredPositionLabel = (typeof MEASURED_POSITION_LABELS)[number]

/** Every measured label, in words. The four grouped labels read as their group. */
export const POSITION_NOUNS: Record<MeasuredPositionLabel, PositionNoun> = {
  QB: GROUP_NOUNS.QB,
  RB: GROUP_NOUNS.RB,
  WR: GROUP_NOUNS.WR,
  TE: GROUP_NOUNS.TE,
  FB: { article: 'a', singular: 'fullback', plural: 'fullbacks' },
  OL: {
    article: 'an',
    singular: 'offensive lineman',
    plural: 'offensive linemen',
  },
  OT: {
    article: 'an',
    singular: 'offensive tackle',
    plural: 'offensive tackles',
  },
  G: { article: 'a', singular: 'guard', plural: 'guards' },
  C: { article: 'a', singular: 'center', plural: 'centers' },
  DL: {
    article: 'a',
    singular: 'defensive lineman',
    plural: 'defensive linemen',
  },
  DE: { article: 'a', singular: 'defensive end', plural: 'defensive ends' },
  DT: {
    article: 'a',
    singular: 'defensive tackle',
    plural: 'defensive tackles',
  },
  NT: { article: 'a', singular: 'nose tackle', plural: 'nose tackles' },
  LB: { article: 'a', singular: 'linebacker', plural: 'linebackers' },
  OLB: {
    article: 'an',
    singular: 'outside linebacker',
    plural: 'outside linebackers',
  },
  ILB: {
    article: 'an',
    singular: 'inside linebacker',
    plural: 'inside linebackers',
  },
  MLB: {
    article: 'a',
    singular: 'middle linebacker',
    plural: 'middle linebackers',
  },
  DB: {
    article: 'a',
    singular: 'defensive back',
    plural: 'defensive backs',
  },
  CB: { article: 'a', singular: 'cornerback', plural: 'cornerbacks' },
  SAF: { article: 'a', singular: 'safety', plural: 'safeties' },
  S: { article: 'a', singular: 'safety', plural: 'safeties' },
  FS: { article: 'a', singular: 'free safety', plural: 'free safeties' },
  K: { article: 'a', singular: 'kicker', plural: 'kickers' },
  P: { article: 'a', singular: 'punter', plural: 'punters' },
  LS: { article: 'a', singular: 'long snapper', plural: 'long snappers' },
}

/** An unknown label, or none at all. */
const ANY_POSITION: PositionNoun = {
  article: 'a',
  singular: 'player at that position',
  plural: 'players at that position',
}

function positionNoun(label: string | null): PositionNoun {
  if (label === null || !Object.hasOwn(POSITION_NOUNS, label)) {
    return ANY_POSITION
  }
  return POSITION_NOUNS[label as MeasuredPositionLabel]
}

function withArticle(noun: PositionNoun): string {
  return `${noun.article} ${noun.singular}`
}

/** "a running back". */
export function groupSingular(group: PlayerPositionGroup): string {
  return withArticle(GROUP_NOUNS[group])
}

/** "a safety", from a position label; generic for an unknown or missing one. */
export function positionSingular(label: string | null): string {
  return withArticle(positionNoun(label))
}

/** "safeties", from a position label; generic for an unknown or missing one. */
export function positionPlural(label: string | null): string {
  return positionNoun(label).plural
}

/** Plain UI text, shown once Player A is picked: who Player B can be. */
export function restrictionCopy(group: PlayerPositionGroup): string {
  const noun = GROUP_NOUNS[group]
  return `Comparing ${noun.plural}. Player B has to be ${withArticle(noun)} too.`
}

/**
 * The narrator refusing a mixed link. `bSingular` is Player B's group
 * (`groupSingular`) or, for a Player B with no group, his position
 * (`positionSingular`): never a group he doesn't have.
 */
export function notComparableCopy(
  aGroup: PlayerPositionGroup,
  bSingular: string,
): string {
  const a = GROUP_NOUNS[aGroup]
  const opening = withArticle(a)
  return `${opening.charAt(0).toUpperCase()}${opening.slice(1)} and ${bSingular}? That's apples and footballs, pal. Pick another ${a.singular}.`
}

/** A Player A with no group: his position, pluralized, can't be compared yet. */
export function uncomparableCopy(label: string | null): string {
  return `Can't stack up ${positionPlural(label)} yet. Quarterbacks, running backs, receivers and tight ends only, for now.`
}

/**
 * Head-to-head counts games two players started at quarterback against each
 * other, so it shows for two quarterbacks only (#372); every other pair gets
 * its career totals alone. Presentation only: the API still sends it.
 */
export function showsHeadToHead(comparison: PlayerComparisonOut): boolean {
  return comparison.a.group === 'QB' && comparison.b.group === 'QB'
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
