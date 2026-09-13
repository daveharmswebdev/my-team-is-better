/**
 * Formats a season (or per-opponent) record for display, following the
 * engine's own record rule (issue #83): `W-L-T` when there is at least one
 * tie (e.g. "6-9-1"), plain `W-L` when there are none (still "13-0").
 *
 * Ties only happen in practice in the NFL, so the zero-tie branch keeps every
 * CFB record exactly as it rendered before ties were carried through -- no
 * trailing "-0" on a college team.
 */
export function formatRecord(
  wins: number,
  losses: number,
  ties: number,
): string {
  return ties > 0 ? `${wins}-${losses}-${ties}` : `${wins}-${losses}`
}
