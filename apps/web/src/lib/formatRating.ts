/**
 * Formats a Keener rating (or rating diff) for display.
 *
 * `rating`/`rating_diff` come from a Perron-Frobenius eigenvector that's
 * normalized so all rated teams' ratings sum to 1
 * (`r_next /= r_next.sum()` in `packages/cfb-engine`'s `ratings/keener.py`),
 * so real values are tiny (e.g. `0.00877`). Scaling by 1000 gives a
 * readable double-digit number in the range the design mockups assume --
 * this is a display-only transform, it does not change the underlying
 * value or its meaning (relative comparisons are unaffected by a constant
 * scale factor).
 */
export function formatRating(rating: number): string {
  return (rating * 1000).toFixed(2)
}
