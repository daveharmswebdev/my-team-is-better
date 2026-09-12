/**
 * Team name matching for `TeamCombobox` -- the ranking/folding rules behind
 * both its suggestion list and `QuestionForm`'s stale-value flag (issue
 * #100), which must agree with each other.
 *
 * A separate module from the component purely so `isTeamInCatalog` can be
 * imported without a component file exporting a non-component (ESLint's
 * `react-refresh/only-export-components`).
 */

import type { TeamDetail } from '../../lib/api/types'

/*
 * Ranking tiers, best first (issue #79): exact match, then canonical-name
 * prefix, then mascot/alias match, then substring anywhere. `RANK_NONE`
 * means "not a match at all" and is filtered out.
 */
const RANK_EXACT = 0
const RANK_NAME_PREFIX = 1
const RANK_MASCOT_OR_ALIAS = 2
const RANK_SUBSTRING = 3
const RANK_NONE = 4

/**
 * Case- and diacritic-insensitive fold for matching only -- never for
 * display or for anything emitted through `onChange`. NFD splits "é" into
 * "e" + a combining accent, which the `\p{Diacritic}` strip then removes, so
 * a user typing "san jose" finds "San José State".
 */
function fold(text: string): string {
  return text
    .normalize('NFD')
    .replace(/\p{Diacritic}/gu, '')
    .toLowerCase()
}

function rankTeam(team: TeamDetail, foldedQuery: string): number {
  const name = fold(team.name)
  const aliases = team.aliases.map(fold)
  if (name === foldedQuery || aliases.includes(foldedQuery)) {
    return RANK_EXACT
  }
  if (name.startsWith(foldedQuery)) {
    return RANK_NAME_PREFIX
  }
  const mascot = team.mascot === null ? null : fold(team.mascot)
  if (mascot !== null && mascot.includes(foldedQuery)) {
    return RANK_MASCOT_OR_ALIAS
  }
  if (aliases.some((alias) => alias.includes(foldedQuery))) {
    return RANK_MASCOT_OR_ALIAS
  }
  if (name.includes(foldedQuery)) {
    return RANK_SUBSTRING
  }
  return RANK_NONE
}

/**
 * True when `value` names a team that is actually in `teams` -- an exact
 * match on the canonical name or on one of its aliases, under the same
 * case/diacritic fold the typeahead matches with. Deliberately *only*
 * `RANK_EXACT`: "Tex" ranks as a match for suggestion purposes, and a
 * mascot ("Longhorns") is never a submitted value.
 *
 * **This is deliberately stricter than the API, and must not be "fixed" to
 * agree with it.** `cfb_strength.evidence.proof.resolve_team` also matches
 * by substring in either direction and by fuzzy match at 0.6, so names this
 * rejects -- "Alabma", "Ohio ST" -- do resolve server-side and return a
 * normal verdict. That divergence is harmless in this direction *because
 * the flag never blocks and never disables submit*: the worst case is a
 * notice next to a value that then submits fine. Loosening this to match
 * `resolve_team` would silently stop flagging genuinely out-of-scope values,
 * which is the defect issue #100 exists to fix. Tightening the API instead
 * would break the documented degrade-to-plain-input path.
 *
 * Exported for `QuestionForm`, which uses it to flag -- never to block -- a
 * team value left over from a different season or league (issue #100). It
 * shares this fold rather than re-deriving one, so the flag cannot disagree
 * with what the typeahead next to it is offering.
 */
export function isTeamInCatalog(teams: TeamDetail[], value: string): boolean {
  const foldedValue = fold(value.trim())
  if (foldedValue === '') {
    return false
  }
  return teams.some((team) => rankTeam(team, foldedValue) === RANK_EXACT)
}

/**
 * Substring (never prefix-only, never fuzzy) match across the canonical
 * name, the mascot, and every alias, ranked by `RANK_*` and then by the
 * caller's original order -- so an ambiguous query like "New York" keeps
 * both the Giants and the Jets, in catalog order, rather than collapsing to
 * one guess.
 */
export function matchTeams(
  teams: TeamDetail[],
  query: string,
  maxResults: number,
): TeamDetail[] {
  const foldedQuery = fold(query.trim())
  if (foldedQuery === '') {
    return teams.slice(0, maxResults)
  }
  const ranked: { team: TeamDetail; rank: number; order: number }[] = []
  teams.forEach((team, order) => {
    const rank = rankTeam(team, foldedQuery)
    if (rank !== RANK_NONE) {
      ranked.push({ team, rank, order })
    }
  })
  ranked.sort((a, b) => a.rank - b.rank || a.order - b.order)
  return ranked.slice(0, maxResults).map((entry) => entry.team)
}
