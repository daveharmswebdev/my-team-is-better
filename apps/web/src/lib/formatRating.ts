import type { Method } from './api/types'

/**
 * Each method's display scale and precision, as data. Mirrored from, and
 * checked against, `apps/api/rating-display.json` (epic #147 / issue #165) by
 * `formatRating.contract.test.ts`. Persona grounding in apps/api accepts a
 * rating quoted the way the card prints it, so it depends on these numbers too:
 * changing either side alone fails CI.
 * - `scale` multiplies a raw value into the printed number's units.
 * - `decimals` is how many fraction digits print.
 */
export interface RatingDisplay {
  scale: number
  decimals: number
}

/**
 * A method's display rule: its `RatingDisplay` data, plus two halves derived
 * from that data so a rating pair can be compared on exactly what prints:
 * - `toUnits` rounds a raw value once, to a whole number of the method's
 *   smallest printed step (Keener: hundredths of the x1000 scale; Elo: points).
 *   Integers subtract exactly, so a diff of two rounded values carries no float
 *   noise (`3.50 - 3.49` would be `0.010000000000000231`).
 * - `formatUnits` prints a unit count. It never prints a signed zero.
 */
interface DisplayRule extends RatingDisplay {
  toUnits: (value: number) => number
  formatUnits: (units: number) => string
}

/** `-0` would print as "-0"/"-0.00"; a zero count is always plain `0`. */
function unsignedZero(units: number): number {
  return units === 0 ? 0 : units
}

/**
 * Keener's method: `rating`/`rating_diff` come from a Perron-Frobenius
 * eigenvector normalized so all rated teams' ratings sum to 1
 * (`r_next /= r_next.sum()` in `packages/cfb-engine`'s `ratings/keener.py`),
 * so real values are tiny (e.g. `0.00877`). Scaling (by 1000) gives a readable
 * double-digit number in the range the design mockups assume, shown to a fixed
 * number of decimals (2). A value that rounds to zero prints `"0.00"`, never
 * `"-0.00"`.
 */
function keenerRule({ scale, decimals }: RatingDisplay): DisplayRule {
  const step = 10 ** decimals
  return {
    scale,
    decimals,
    // Units are read straight off `toFixed`'s digits ("3.50" -> 350), not from
    // `Math.round(value * scale * step)`: the two disagree on binary
    // half-boundaries (`0.003505` is "3.50" via toFixed but 351 via
    // Math.round), and the printed string is the one that must stay
    // authoritative.
    toUnits: (value) =>
      unsignedZero(Number((value * scale).toFixed(decimals).replace('.', ''))),
    formatUnits: (units) => (unsignedZero(units) / step).toFixed(decimals),
  }
}

/**
 * Elo (single-season or career): ratings sit around 1500 on their own
 * points scale, so they're shown as whole points (scale 1, 0 decimals) with a
 * thousands separator (`1684.4` -> `"1,684"`). A value that rounds to zero
 * prints `"0"`, never `"-0"`. `Math.round` takes halves toward +infinity
 * (`-12.5` -> `-12`); that one rule applies to every value, so a pair's printed
 * order never flips.
 */
function eloRule({ scale, decimals }: RatingDisplay): DisplayRule {
  const step = 10 ** decimals
  const format = new Intl.NumberFormat('en-US', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  })
  return {
    scale,
    decimals,
    toUnits: (value) => unsignedZero(Math.round(value * scale * step)),
    formatUnits: (units) => format.format(unsignedZero(units) / step),
  }
}

/**
 * One display rule per rating method. Exhaustive on purpose: a method added to
 * `METHODS` fails to type-check here until it picks a display scale.
 */
const DISPLAY_RULES: Record<Method, DisplayRule> = {
  keener: keenerRule({ scale: 1000, decimals: 2 }),
  elo: eloRule({ scale: 1, decimals: 0 }),
  elo_career: eloRule({ scale: 1, decimals: 0 }),
}

function displayData({ scale, decimals }: RatingDisplay): RatingDisplay {
  return Object.freeze({ scale, decimals })
}

/**
 * Every method's `scale`/`decimals`, read off `DISPLAY_RULES` (so it is the data
 * the rules actually print with) for the contract test against
 * `apps/api/rating-display.json`.
 */
export const RATING_DISPLAY_DATA: Readonly<
  Record<Method, Readonly<RatingDisplay>>
> = Object.freeze({
  keener: displayData(DISPLAY_RULES.keener),
  elo: displayData(DISPLAY_RULES.elo),
  elo_career: displayData(DISPLAY_RULES.elo_career),
})

/**
 * Formats a rating (or a rating diff) for display on its method's own scale.
 * The two scales are not comparable: Keener's eigenvector sums to 1 across all
 * teams, while Elo ratings sit around 1500. Display-only -- the underlying
 * value and its meaning are unchanged, and relative comparisons within one
 * method are unaffected.
 */
export function formatRating(value: number, method: Method): string {
  const rule = DISPLAY_RULES[method]
  return rule.formatUnits(rule.toUnits(value))
}

/** Two ratings as printed, their printed diff, and which one prints larger. */
export interface DisplayedRatingPair {
  /** `formatRating(a, method)`. */
  a: string
  /** `formatRating(b, method)`. */
  b: string
  /** Printed a minus printed b, in the same format; zero exactly when `a === b`. */
  diff: string
  /** The side with the larger printed rating, or `null` when both print the same. */
  leader: 'a' | 'b' | null
}

/**
 * Compares two ratings on exactly what prints. Each is rounded once to its
 * method's display step. The diff, the "same" test and the leader all come from
 * those rounded values, never from the raw values or a raw diff. A raw diff
 * rounded on its own can disagree with the two printed ratings: Elo `1531.5` vs
 * `1531.4` prints "1,532 vs 1,531" but a raw diff of "0".
 */
export function displayRatingPair(
  a: number,
  b: number,
  method: Method,
): DisplayedRatingPair {
  const rule = DISPLAY_RULES[method]
  const unitsA = rule.toUnits(a)
  const unitsB = rule.toUnits(b)
  const diffUnits = unitsA - unitsB
  return {
    a: rule.formatUnits(unitsA),
    b: rule.formatUnits(unitsB),
    diff: rule.formatUnits(diffUnits),
    leader: diffUnits === 0 ? null : diffUnits > 0 ? 'a' : 'b',
  }
}
