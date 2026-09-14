import type { EloLedgerOut, Method } from '../../lib/api/types'

/**
 * What a rating method can honestly show behind its rating (issues #153,
 * #183):
 * - `keener-breakdown`: `RatingBreakdownDisclosure`'s per-opponent credit.
 * - `elo-ledger`: `EloLedgerDisclosure`'s game-by-game work.
 * - `no-disclosure`: nothing to open; the receipts print `explainer` instead.
 */
export type RatingBreakdownSupport =
  | { kind: 'keener-breakdown' }
  | { kind: 'elo-ledger' }
  | { kind: 'no-disclosure'; explainer: string }

export const ELO_CAREER_EXPLAINER =
  "Career Elo carries ratings across seasons, and its game-by-game work isn't shown yet."

/** Printed beside a plain Elo rating when the response carries no ledger (a stale API or db). */
export const ELO_LEDGER_UNAVAILABLE =
  "This rating's game-by-game work isn't available right now."

/**
 * Decided by **method**, never inferred from the response's shape: Elo
 * writes no breakdown rows, so its breakdown deserializes to
 * `{entries: [], residual_contribution: 0}` -- but a Keener team can
 * legitimately have that shape too, and still deserves its disclosure.
 *
 * Exhaustive on purpose: a method added to `METHODS` fails tsc here until
 * someone decides what it has to show.
 */
export const RATING_BREAKDOWN_BY_METHOD: Record<
  Method,
  RatingBreakdownSupport
> = {
  keener: { kind: 'keener-breakdown' },
  elo: { kind: 'elo-ledger' },
  // Unreachable from the UI (the Engine toggle doesn't offer it), but typed.
  elo_career: { kind: 'no-disclosure', explainer: ELO_CAREER_EXPLAINER },
}

/**
 * What one team's rating renders as: the method's support, resolved against
 * that team's own `elo_ledger`.
 * - `no-disclosure`'s explainer is about the method, so a receipts block
 *   prints it once.
 * - `ledger-unavailable`'s note is about one team's response, so it prints
 *   beside that team's rating. A missing ledger never becomes an empty or
 *   invented panel.
 */
export type RatingWork =
  | { kind: 'keener-breakdown' }
  | { kind: 'elo-ledger'; ledger: EloLedgerOut }
  | { kind: 'no-disclosure'; explainer: string }
  | { kind: 'ledger-unavailable'; note: string }

export function ratingWorkFor(
  method: Method,
  eloLedger: EloLedgerOut | null | undefined,
): RatingWork {
  const support = RATING_BREAKDOWN_BY_METHOD[method]
  switch (support.kind) {
    case 'keener-breakdown':
    case 'no-disclosure':
      return support
    case 'elo-ledger':
      if (eloLedger === null || eloLedger === undefined) {
        return { kind: 'ledger-unavailable', note: ELO_LEDGER_UNAVAILABLE }
      }
      return { kind: 'elo-ledger', ledger: eloLedger }
  }
}
