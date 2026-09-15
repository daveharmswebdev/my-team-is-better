/**
 * The element id of a methodology's article on the About page, slugged from
 * the display name `/api/credits` sends: "Elo" -> `elo`, "Keener's method"
 * -> `keeners-method`. Lower-cased, apostrophes dropped (so the possessive
 * doesn't split into "keener-s"), every other run of non-alphanumerics
 * becomes one hyphen, and the ends are trimmed.
 *
 * These ids are link targets -- `EloLedgerDisclosure`'s provenance line
 * points at `/about#elo` (issue #227) -- so they are an interim coupling on
 * the API's display name. If #144 makes `CreditsOut` publish each
 * methodology's `methods` tuple, switch the id source to that key and
 * delete this.
 */
export function methodologyId(name: string): string {
  return name
    .toLowerCase()
    .replace(/'/g, '')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
}
