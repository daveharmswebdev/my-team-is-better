import type { Method } from './api/types'

const ELO_FORMAT = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 })

/**
 * A method's display rule, split into its two halves so a rating pair can be
 * compared on exactly what prints:
 * - `toUnits` rounds a raw value once, to a whole number of the method's
 *   smallest printed step (Keener: hundredths of the x1000 scale; Elo: points).
 *   Integers subtract exactly, so a diff of two rounded values carries no float
 *   noise (`3.50 - 3.49` would be `0.010000000000000231`).
 * - `formatUnits` prints a unit count. It never prints a signed zero.
 */
interface DisplayRule {
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
 * so real values are tiny (e.g. `0.00877`). Scaling by 1000 gives a readable
 * double-digit number in the range the design mockups assume, shown to 2
 * decimals. A value that rounds to zero prints `"0.00"`, never `"-0.00"`.
 */
const KEENER: DisplayRule = {
  // Units are read straight off `toFixed`'s digits ("3.50" -> 350), not from
  // `Math.round(value * 1e5)`: the two disagree on binary half-boundaries
  // (`0.003505` is "3.50" via toFixed but 351 via Math.round), and the printed
  // string is the one that must stay authoritative.
  toUnits: (value) =>
    unsignedZero(Number((value * 1000).toFixed(2).replace('.', ''))),
  formatUnits: (units) => (unsignedZero(units) / 100).toFixed(2),
}

/**
 * Elo (single-season or career): ratings sit around 1500 on their own
 * points scale, so they're shown as whole points with a thousands separator
 * (`1684.4` -> `"1,684"`). A value that rounds to zero prints `"0"`, never
 * `"-0"`. `Math.round` takes halves toward +infinity (`-12.5` -> `-12`); that
 * one rule applies to every value, so a pair's printed order never flips.
 */
const ELO: DisplayRule = {
  toUnits: (value) => unsignedZero(Math.round(value)),
  formatUnits: (units) => ELO_FORMAT.format(unsignedZero(units)),
}

/**
 * One display rule per rating method. Exhaustive on purpose: a method added to
 * `METHODS` fails to type-check here until it picks a display scale.
 */
const DISPLAY_RULES: Record<Method, DisplayRule> = {
  keener: KEENER,
  elo: ELO,
  elo_career: ELO,
}

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
