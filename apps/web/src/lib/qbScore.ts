/**
 * The era-adjusted QB score's copy and number formatting (issue #459, epic
 * #439). The math decides and the narrator explains: every winner, margin,
 * score, z and weight here is read off the API's `qb_score` and only
 * printed -- nothing is compared, summed or re-derived on the client.
 *
 * Copy is the bar-stool narrator's (founder rules: #231 "the numbers are the
 * numbers", and error lines in voice, never a raw status).
 */
import {
  PlayerApiError,
  PlayersNotComparableError,
  VerdictHttpError,
  VerdictNetworkError,
} from './api/client'
import type { PlayerQbScoreComparisonOut, QbScoreSide } from './api/types'

/** U+2212, so a negative reads as "minus" and lines up with the digits. */
const MINUS = '−'

/** `value` to `decimals` places, with a real minus sign and never "-0.00". */
function formatSigned(value: number, decimals: number): string {
  const text = Math.abs(value).toFixed(decimals)
  return value < 0 && Number(text) !== 0 ? `${MINUS}${text}` : text
}

/** A career, peak or season score: 2 decimals, as the narration says it. */
export function formatQbScore(value: number): string {
  return formatSigned(value, 2)
}

/**
 * A margin as the narration says it, "by 0.10": its absolute value to 2
 * decimals. The API's margins are signed (`a - b`), and the winner's name
 * already says which way it went.
 */
export function formatQbMargin(margin: number): string {
  return Math.abs(margin).toFixed(2)
}

/** A weight as the API sent it, trimmed of float noise: 0.826, 0.5. */
export function formatQbWeight(weight: number): string {
  return String(Number(weight.toFixed(3)))
}

/** A z-score: 2 decimals, signed. */
export function formatQbZ(z: number): string {
  return formatSigned(z, 2)
}

/** An EPA value, mean or SD: 3 decimals, since they live near zero. */
export function formatQbEpa(value: number): string {
  return formatSigned(value, 3)
}

/** An ANY/A value, mean or SD: 2 decimals, like yards per attempt. */
export function formatQbAnyA(value: number): string {
  return formatSigned(value, 2)
}

/** The two measures a panel shows. */
export type QbMeasure = 'career' | 'peak'

/** Said when the API names no winner beside a margin: an exact tie. */
export const QB_TIE_COPY = 'Dead even'

function nameOf(qbScore: PlayerQbScoreComparisonOut, side: QbScoreSide) {
  return qbScore[side].display_name
}

/**
 * Who takes a measure and by how much, "Tom Brady by 0.10", from the API's
 * `*_winner` and `*_margin`. A `null` winner on a conclusive comparison is an
 * exact tie. (An inconclusive one has no edge at all: see
 * `qbInconclusiveCopy`.)
 */
export function qbMeasureEdge(
  qbScore: PlayerQbScoreComparisonOut,
  measure: QbMeasure,
): string {
  const winner =
    measure === 'career' ? qbScore.career_winner : qbScore.peak_winner
  const margin =
    measure === 'career' ? qbScore.career_margin : qbScore.peak_margin
  if (winner === null || margin === null) {
    return QB_TIE_COPY
  }
  return `${nameOf(qbScore, winner)} by ${formatQbMargin(margin)}`
}

const INCONCLUSIVE = "The body of work isn't there — inconclusive."

/**
 * Why there's no score, in voice, when either QB has no qualifying season;
 * `null` when both have one. The closing line is the founder's (#439).
 */
export function qbInconclusiveCopy(
  qbScore: PlayerQbScoreComparisonOut,
): string | null {
  const rule = `${qbScore.min_dropbacks} or more dropbacks`
  switch (qbScore.inconclusive) {
    case null:
      return null
    case 'a_no_qualifying_season':
    case 'b_no_qualifying_season': {
      const side = qbScore.inconclusive === 'a_no_qualifying_season' ? 'a' : 'b'
      return `${nameOf(qbScore, side)} has no season in our books with ${rule}, so there's no score to put up. ${INCONCLUSIVE}`
    }
    case 'neither_has_qualifying_season':
      return `Neither one has a season in our books with ${rule}, so there's nothing to score. ${INCONCLUSIVE}`
  }
}

/**
 * The 1999 floor, said every time the score shows: plainly, or -- for the
 * careers that began before the data (`coverage.cut_off`, the signal #448's
 * callout already uses) -- by name, so it's louder. `null` on a db with no
 * stat rows, which has no floor to state.
 */
export function qbFloorLine(
  dataFirstSeason: number | null,
  cutOffNames: readonly string[],
): string | null {
  if (dataFirstSeason === null) {
    return null
  }
  const y = dataFirstSeason
  const tail = `and the play-by-play doesn't go back that far`
  if (cutOffNames.length >= 2) {
    return `Both careers started before ${y}, ${tail}: only their seasons from ${y} on are scored.`
  }
  const [name] = cutOffNames
  if (name !== undefined) {
    return `${name}'s career started before ${y}, ${tail}: only his seasons from ${y} on are scored.`
  }
  return `Counted since ${y}, where the play-by-play starts.`
}

/** How the weights were fitted: static copy, measured on #440. */
export const QB_WEIGHT_FIT_COPY =
  "an OLS fit of next season's EPA per play on this season's two z-scores, 629 consecutive QB-season pairs, 1999–2025"

/** While the narration is on its way; the score is already up. */
export const QB_NARRATION_LOADING_COPY = "Hang on, I'm reading the numbers…"

/** Every narration failure ends on the founder's line: the score stands. */
const THE_NUMBERS = 'The numbers up there are the numbers.'

/**
 * What the narrator says when his narration can't be had (issue #459). The
 * score panel stays up whatever happened, so each line points back at it.
 * Never a raw status: the class of failure picks the line, and the status
 * and body stay on the error, for developers.
 */
export function qbNarrationErrorCopy(error: unknown): string {
  if (error instanceof PlayersNotComparableError) {
    return `I only call these for two quarterbacks, so I'm sitting this one out. ${THE_NUMBERS}`
  }
  if (error instanceof PlayerApiError) {
    return `I lost one of these two in my book, so no call from me. ${THE_NUMBERS}`
  }
  if (error instanceof VerdictNetworkError) {
    return `Lost you there, pal. My two cents didn't make it through. ${THE_NUMBERS}`
  }
  if (
    error instanceof VerdictHttpError &&
    error.status >= 400 &&
    error.status < 500
  ) {
    return `Your question came through garbled before I could weigh in. ${THE_NUMBERS}`
  }
  return `Something broke in the back before I could say my piece. ${THE_NUMBERS}`
}
