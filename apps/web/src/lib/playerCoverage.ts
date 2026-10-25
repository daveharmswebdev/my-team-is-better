/**
 * How much of a career the data holds, said out loud (issue #448, epic
 * #443). The API's `coverage` (#446) says when a career began before the
 * db's player stats (`cut_off`) or runs past them (`cut_off_after`); this
 * module turns that into the page's copy and the founder's marking rule.
 * Every number, year and name comes from `coverage` and the player's
 * `display_name`, never typed in, so the wording changes here and only here.
 *
 * The copy is the coordinator's voice call on #448: the bar-stool narrator,
 * facts first, and it never argues with the numbers -- it says which
 * numbers aren't there.
 */
import type { PlayerCoverageOut } from './api/types'
import { formatSeasonSpan } from './playerStats'

/** A player as the copy names him. */
export interface CoveredPlayer {
  name: string
  coverage: PlayerCoverageOut
}

/** What a cut-off sentence needs, all known: `cut_off` implies each one. */
interface CutOffFacts {
  careerFirst: number
  careerLast: number
  careerSeasons: number
  dataFirst: number
  covered: number
}

function cutOffFacts(coverage: PlayerCoverageOut): CutOffFacts | null {
  const {
    cut_off: cutOff,
    career_first_season: careerFirst,
    career_last_season: careerLast,
    career_seasons: careerSeasons,
    data_first_season: dataFirst,
    covered_seasons: covered,
  } = coverage
  if (
    !cutOff ||
    careerFirst === null ||
    careerLast === null ||
    careerSeasons === null ||
    dataFirst === null
  ) {
    return null
  }
  return { careerFirst, careerLast, careerSeasons, dataFirst, covered }
}

const NO_CROWNING = "Nobody's crowning anybody on those totals."

/**
 * The compare page's callout, above the tables, when either player's career
 * began before the data; `null` when neither did. Running past the data
 * (`cut_off_after`) alone is not a cut-off: see `statsThroughLine`.
 */
export function compareCallout(
  a: CoveredPlayer,
  b: CoveredPlayer,
): string | null {
  const aFacts = cutOffFacts(a.coverage)
  const bFacts = cutOffFacts(b.coverage)
  if (aFacts !== null && bFacts !== null) {
    return [
      `Hold on. Both of these guys were playing before our books open in ${aFacts.dataFirst}.`,
      `${a.name}: last ${aFacts.covered} of ${aFacts.careerSeasons} seasons.`,
      `${b.name}: last ${bFacts.covered} of ${bFacts.careerSeasons}.`,
      'Slices of careers, not careers.',
      NO_CROWNING,
    ].join(' ')
  }
  const [name, facts] = aFacts !== null ? [a.name, aFacts] : [b.name, bFacts]
  if (facts === null) {
    return null
  }
  return [
    `Hold on. ${name} played ${facts.careerFirst} to ${facts.careerLast}, and our books open in ${facts.dataFirst}.`,
    `That's his last ${facts.covered} of ${facts.careerSeasons} seasons up there, not the whole career.`,
    NO_CROWNING,
  ].join(' ')
}

/** The career page's callout, above the tables; `null` unless cut off. */
export function careerCallout(player: CoveredPlayer): string | null {
  const facts = cutOffFacts(player.coverage)
  if (facts === null) {
    return null
  }
  const missing = facts.careerSeasons - facts.covered
  const sentences = [
    `${player.name} played ${facts.careerFirst} to ${facts.careerLast}.`,
    `Our books open in ${facts.dataFirst}, so this is his last ${facts.covered} of ${facts.careerSeasons} seasons.`,
  ]
  if (missing > 0) {
    sentences.push(
      `The first ${missing} aren't here, and yelling at the bartender won't change it.`,
    )
  }
  return sentences.join(' ')
}

/**
 * A plain line, not the callout, when a career runs past the data (an
 * active player whose current season isn't in yet); `null` otherwise.
 */
export function statsThroughLine(
  coverages: readonly PlayerCoverageOut[],
): string | null {
  const past = coverages.find(
    (coverage) => coverage.cut_off_after && coverage.data_last_season !== null,
  )
  return past === undefined
    ? null
    : `Stats through ${past.data_last_season}. This season isn't in our books yet.`
}

/** "NFL player stats: 1999–2025.", from the db's data span; `null` without one. */
export function dataSpanLine(
  first: number | null,
  last: number | null,
): string | null {
  return first === null || last === null
    ? null
    : `NFL player stats: ${formatSeasonSpan(first, last)}.`
}

/** The real career span from the source's roster, "1990–2004"; `null` when unknown. */
export function careerSpanText(coverage: PlayerCoverageOut): string | null {
  const { career_first_season: first, career_last_season: last } = coverage
  return first === null || last === null ? null : formatSeasonSpan(first, last)
}

/**
 * A cut-off career's seasons cell, "6 of 15 (1999–2004)": the seasons in
 * the books of the seasons he played, and which they are. `null` when not
 * cut off, so the cell shows its plain count.
 */
export function coveredSeasonsText(coverage: PlayerCoverageOut): string | null {
  const facts = cutOffFacts(coverage)
  const { covered_first_season: first, covered_last_season: last } = coverage
  if (facts === null || first === null || last === null) {
    return null
  }
  return `${facts.covered} of ${facts.careerSeasons} (${formatSeasonSpan(first, last)})`
}

/**
 * A search row's span: for a cut-off career, the real one and where its
 * stats start, "1990–2004 · stats from 1999"; otherwise the row's own.
 */
export function searchSpanText(row: {
  first_season: number
  last_season: number
  coverage: PlayerCoverageOut
}): string {
  const facts = cutOffFacts(row.coverage)
  return facts === null
    ? formatSeasonSpan(row.first_season, row.last_season)
    : `${formatSeasonSpan(facts.careerFirst, facts.careerLast)} · stats from ${facts.dataFirst}`
}

/** The visible mark on a leaders row whose career began before the data. */
export const CUT_OFF_GLYPH = '‹'

/**
 * The leaders page's key to `CUT_OFF_GLYPH`, for the board on screen when
 * any of its rows is cut off; `null` when none is. Plain UI text.
 */
export function cutOffLegend(
  coverages: readonly PlayerCoverageOut[],
): string | null {
  const facts = coverages
    .map(cutOffFacts)
    .find((fact): fact is CutOffFacts => fact !== null)
  return facts === undefined
    ? null
    : `${CUT_OFF_GLYPH} marks a career that began before ${facts.dataFirst}: those totals are missing its early seasons.`
}

/** A leaders row's marker label, "career began before 1999"; `null` unless cut off. */
export function cutOffMarkerLabel(coverage: PlayerCoverageOut): string | null {
  const facts = cutOffFacts(coverage)
  return facts === null ? null : `career began before ${facts.dataFirst}`
}

/**
 * What a compared row measures: a career `total` (a count or sum over every
 * season, which a cut-off career is missing seasons of) or a `rate` over the
 * covered seasons, which stays comparable.
 */
export type RowKind = 'total' | 'rate'

/**
 * The founder's rule (#448): no larger-number mark on a career total when
 * either side is cut off; a rate keeps its mark, and so does a career that
 * only runs past the data (`cut_off_after`).
 */
export function marksRow(
  kind: RowKind,
  a: PlayerCoverageOut,
  b: PlayerCoverageOut,
): boolean {
  return kind === 'rate' || (!a.cut_off && !b.cut_off)
}
