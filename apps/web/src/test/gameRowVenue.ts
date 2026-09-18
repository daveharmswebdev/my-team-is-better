/**
 * Fixture invariant for team-relative game rows (issue #294).
 *
 * The API publishes `venue` -- this team's own side, like `result` and the
 * score pair, never a stadium -- on `OpponentResultOut` and
 * `CommonOpponentMeetingOut`, and keeps `neutral_site` beside it on the
 * first. Production cannot emit a disagreeing pair: "neutral" takes
 * precedence over home/away and the engine dataclass raises on a pair that
 * disagrees, so `neutral_site === (venue === 'neutral')` holds on every row
 * the server sends. A fixture that disagrees is a shape production never
 * sends, and would let a real bug pass.
 *
 * `HeadToHeadMeetingOut` is deliberately not team-relative -- it names
 * `home_team` and `away_team` outright -- so it carries `neutral_site` and no
 * `venue`, and a fixture that adds one has drifted from the API.
 */

export const VENUES = ['home', 'away', 'neutral'] as const

export type Venue = (typeof VENUES)[number]

export interface CollectedGameRow {
  /** Where the row sat in the walked value, e.g. `evidence.games[2]`. */
  path: string
  /** `team-relative` rows own a `venue`; `head-to-head` rows must not. */
  kind: 'team-relative' | 'head-to-head'
  venue: unknown
  neutral_site: unknown
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

/** An `OpponentResultOut` / `CommonOpponentMeetingOut`-shaped object. */
function isTeamRelativeRow(value: Record<string, unknown>): boolean {
  return (
    typeof value.game_id === 'number' &&
    typeof value.result === 'string' &&
    typeof value.team_score === 'number' &&
    typeof value.opponent_score === 'number'
  )
}

/** A `HeadToHeadMeetingOut`-shaped object: sides named, not team-relative. */
function isHeadToHeadRow(value: Record<string, unknown>): boolean {
  return (
    typeof value.game_id === 'number' &&
    typeof value.home_team === 'string' &&
    typeof value.away_team === 'string'
  )
}

/**
 * Every game row reachable from `value`, however deeply nested. Functions are
 * never called, so a row a helper builds is only seen through a value that
 * helper was actually used to build.
 */
export function collectGameRows(
  value: unknown,
  rootLabel: string,
): CollectedGameRow[] {
  const rows: CollectedGameRow[] = []
  const seen = new WeakSet<object>()

  function walk(node: unknown, path: string): void {
    if (!isRecord(node) || seen.has(node)) return
    seen.add(node)

    if (Array.isArray(node)) {
      node.forEach((entry, index) => {
        walk(entry, `${path}[${index}]`)
      })
      return
    }

    if (isTeamRelativeRow(node)) {
      rows.push({
        path,
        kind: 'team-relative',
        venue: node.venue,
        neutral_site: node.neutral_site,
      })
    } else if (isHeadToHeadRow(node)) {
      rows.push({
        path,
        kind: 'head-to-head',
        venue: node.venue,
        neutral_site: node.neutral_site,
      })
    }

    for (const [key, child] of Object.entries(node)) {
      walk(child, `${path}.${key}`)
    }
  }

  walk(value, rootLabel)
  return rows
}

/** Why these rows could not have come from the API, one line each. */
export function venueProblems(rows: CollectedGameRow[]): string[] {
  return rows.flatMap((row) => {
    if (row.kind === 'head-to-head') {
      return row.venue === undefined
        ? []
        : [
            `${row.path}: a head-to-head meeting carries no venue (it names home_team/away_team); got ${JSON.stringify(row.venue)}`,
          ]
    }
    if (!VENUES.includes(row.venue as Venue)) {
      return [
        `${row.path}: venue must be one of ${VENUES.join('/')}; got ${JSON.stringify(row.venue)}`,
      ]
    }
    if (row.neutral_site === undefined) return []
    if (typeof row.neutral_site !== 'boolean') {
      return [
        `${row.path}: neutral_site must be a boolean; got ${JSON.stringify(row.neutral_site)}`,
      ]
    }
    return row.neutral_site === (row.venue === 'neutral')
      ? []
      : [
          `${row.path}: neutral_site ${row.neutral_site} disagrees with venue ${JSON.stringify(row.venue)} -- the API cannot send this pair`,
        ]
  })
}
