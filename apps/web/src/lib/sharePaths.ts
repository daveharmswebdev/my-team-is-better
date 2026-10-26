/**
 * Where a Share button's link points (issue #185). A minted link sits under
 * `/s` on the web origin; there, the web's proxy serves the API's preview page
 * (per-link Open Graph text for an unfurl), which redirects a person on to the
 * SPA page the rest of the path names. Where no proxy runs (vite dev, vite
 * preview, the e2e server), the SPA's own `/s` routes in `App.tsx` do that
 * redirect instead.
 *
 * Only the path is new: the query string is the page's own, byte for byte,
 * and the old `/?…` and `/nfl/compare?…` links keep working unchanged
 * (docs/ARCHITECTURE.md section 5.1).
 */

/** The prefix of every minted share link. */
const SHARE_PREFIX = '/s'

/** The SPA page a verdict link opens. */
export const VERDICT_PAGE_PATH = '/'

/** The SPA page a player-comparison link opens. */
export const COMPARE_PAGE_PATH = '/nfl/compare'

/** A verdict's share path; the SPA lands it on {@link VERDICT_PAGE_PATH}. */
export const VERDICT_SHARE_PATH = SHARE_PREFIX

/** A comparison's share path; the SPA lands it on {@link COMPARE_PAGE_PATH}. */
export const COMPARE_SHARE_PATH = `${SHARE_PREFIX}${COMPARE_PAGE_PATH}`

/** A verdict's share link, given the share query string with no leading `?`. */
export function verdictShareUrl(origin: string, search: string): string {
  return `${origin}${VERDICT_SHARE_PATH}?${search}`
}

/** A player comparison's share link, players `a` then `b`. */
export function compareShareUrl(origin: string, a: number, b: number): string {
  return `${origin}${COMPARE_SHARE_PATH}?a=${a}&b=${b}`
}
