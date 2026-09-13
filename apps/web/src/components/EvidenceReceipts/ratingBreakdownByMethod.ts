import type { Method } from '../../lib/api/types'

/**
 * Whether a rating method produces a per-opponent breakdown that
 * `RatingBreakdownDisclosure` can honestly show, and if not, the one line the
 * receipts print instead (issue #153).
 */
export type RatingBreakdownSupport =
  { hasBreakdown: true } | { hasBreakdown: false; explainer: string }

const ELO_EXPLAINER =
  'Elo builds its rating game by game, in date order, with margin of victory counted — it has no per-opponent breakdown to show.'

/**
 * Decided by **method**, never inferred from the breakdown's emptiness: Elo
 * writes no breakdown rows, so its breakdown deserializes to
 * `{entries: [], residual_contribution: 0}` -- but a Keener team can
 * legitimately have that shape too, and still deserves its disclosure.
 *
 * Exhaustive on purpose: a method added to `METHODS` fails tsc here until
 * someone decides whether it has a breakdown to show.
 */
export const RATING_BREAKDOWN_BY_METHOD: Record<
  Method,
  RatingBreakdownSupport
> = {
  keener: { hasBreakdown: true },
  elo: { hasBreakdown: false, explainer: ELO_EXPLAINER },
  // Unreachable from the UI (the Engine toggle doesn't offer it), but typed.
  elo_career: { hasBreakdown: false, explainer: ELO_EXPLAINER },
}
