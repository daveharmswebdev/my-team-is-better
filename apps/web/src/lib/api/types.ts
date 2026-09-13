/**
 * TypeScript mirror of `apps/api/src/api/models.py`'s response/error shapes.
 * Field names and nesting intentionally match the Python source exactly --
 * see that file for the source of truth; this file is not a substitute for
 * reading it.
 */

/**
 * A single completed game's result from one team's side. `'T'` is a tie
 * (equal scores, any sport -- issue #83); it can appear in `games` and in
 * common-opponent results, but never in `quality_wins` or `worst_loss`.
 */
export type GameResult = 'W' | 'L' | 'T'

export interface OpponentResultOut {
  opponent_team_id: number
  opponent_name: string
  opponent_rank: number | null
  opponent_rating: number | null
  result: GameResult
  team_score: number
  opponent_score: number
  week: number | null
  season_type: string
  neutral_site: boolean
}

export interface OpponentCreditOut {
  opponent_team_id: number
  opponent_name: string
  games_played: number
  wins: number
  losses: number
  credit: number
  contribution: number
  explanation: string
}

export interface RatingBreakdownOut {
  entries: OpponentCreditOut[]
  residual_contribution: number
}

export interface TeamCaseOut {
  year: number
  method: string
  team_id: number
  team_name: string
  rank: number
  rating: number
  wins: number
  losses: number
  /** Required on the API side (issue #83). Render records via `formatRecord`. */
  ties: number
  rating_breakdown: RatingBreakdownOut
  games: OpponentResultOut[]
  quality_wins: OpponentResultOut[]
  worst_loss: OpponentResultOut | null
}

export interface ComparisonTeamSummaryOut {
  team_id: number
  team_name: string
  rank: number
  rating: number
  wins: number
  losses: number
  /** Required on the API side (issue #83). Render records via `formatRecord`. */
  ties: number
  rating_breakdown: RatingBreakdownOut
  quality_wins: OpponentResultOut[]
  worst_loss: OpponentResultOut | null
}

export interface HeadToHeadMeetingOut {
  week: number | null
  season_type: string
  neutral_site: boolean
  home_team: string
  away_team: string
  home_points: number
  away_points: number
  winner: string | null
}

export interface HeadToHeadOut {
  played: boolean
  meetings: HeadToHeadMeetingOut[]
}

export interface CommonOpponentOut {
  opponent_team_id: number
  opponent_name: string
  opponent_rank: number | null
  team_a_result: GameResult
  team_a_score: number
  team_a_opponent_score: number
  team_b_result: GameResult
  team_b_score: number
  team_b_opponent_score: number
}

export interface ComparisonResultOut {
  year: number
  team_a: ComparisonTeamSummaryOut
  team_b: ComparisonTeamSummaryOut
  head_to_head: HeadToHeadOut
  common_opponents: CommonOpponentOut[]
  rating_diff: number
  verdict: string
}

export interface NarrationOut {
  text: string
  contested: boolean
  cached: boolean
}

export interface TeamCaseEnvelope {
  evidence: TeamCaseOut
  narration: NarrationOut
}

export interface ComparisonEnvelope {
  evidence: ComparisonResultOut
  narration: NarrationOut
}

export type VerdictEnvelope = TeamCaseEnvelope | ComparisonEnvelope

// ---------------------------------------------------------------------------
// credits -- mirrors apps/api/src/api/models.py's `CreditsOut` (About page).
// ---------------------------------------------------------------------------

export interface CreditsMethodologyOut {
  name: string
  citation: string
  url: string
  summary: string
}

export interface CreditsDataSourceOut {
  name: string
  url: string
  note: string
}

export interface CreditsOut {
  /**
   * Every rating method the engine implements, in the order the API sends
   * them -- Keener's method (the validated default) first, then Elo (the
   * second opinion). Render in the order received; do not sort.
   */
  methodologies: CreditsMethodologyOut[]
  data_sources: CreditsDataSourceOut[]
}

// ---------------------------------------------------------------------------
// catalog -- mirrors apps/api/src/api/models.py's `YearsOut`/`TeamsOut`
// (`/api/years`, `/api/teams`), the year/team picker's valid-selection
// universe (`QuestionForm`'s year suggestions and `TeamCombobox` fields).
// ---------------------------------------------------------------------------

export interface YearsOut {
  years: number[]
}

/**
 * Mirrors `apps/api`'s `TeamsOut`: `teams` is the canonical flat
 * submitted-value list and stays exactly as it was, while `team_details`
 * (epic #76 / issue #78) is a parallel array of the same names in the same
 * order plus display metadata. Both arrays come from one query on the API
 * side, so they cannot drift and may be zipped by index -- `QuestionForm`
 * feeds `team_details` to `TeamCombobox` and nothing reads the two together.
 */
export interface TeamsOut {
  teams: string[]
  team_details: TeamDetail[]
}

/**
 * One team's display/matching detail -- mirrors the per-team rows
 * `/api/teams` returns alongside `TeamsOut`'s flat name list (epic #76).
 * `name` is the canonical `teams.school` string and is the only thing a
 * picker ever submits: byte-identical, because the verdict lookup, the
 * persona grounding check, the golden dataset, and every cached narration
 * key are keyed on it. `mascot` is `null` for every NFL team (the canonical
 * name already contains city + nickname) and for a handful of CFB teams;
 * `aliases` holds deduped abbreviations/alternate spellings and may be empty.
 */
export interface TeamDetail {
  name: string
  mascot: string | null
  aliases: string[]
}

// ---------------------------------------------------------------------------
// sport -- mirrors the API's `Sport` Literal (re-exported by
// `apps/api/src/api/models.py` from the engine's `cfb_strength.contracts`),
// used on the catalog and verdict request models and on `unknown_team`.
// `QuestionForm`'s College/NFL toggle (issue #60) is the only producer of a
// non-default value today.
// ---------------------------------------------------------------------------

/**
 * The one hand-written sport list in apps/web: `Sport` and the runtime guard
 * behind `isVerdictErrorBody` both derive from it. Checked against the API's
 * published `apps/api/openapi-vocabularies.json` (`sport`, order included) by
 * `vocabularies.test.ts` (issue #112), so a league the API gains without
 * apps/web following it fails CI rather than silently degrading a mapped 404
 * into a generic error.
 */
export const SPORTS = ['cfb', 'nfl'] as const

export type Sport = (typeof SPORTS)[number]

/** True when `evidence` is a `TeamCaseOut` (champion/team-case routes) rather than a `ComparisonResultOut` (compare route). */
export function isTeamCaseEnvelope(
  envelope: VerdictEnvelope,
): envelope is TeamCaseEnvelope {
  return 'team_id' in envelope.evidence
}

// ---------------------------------------------------------------------------
// error bodies -- mirrors apps/api/src/api/errors.py's four mapped cases.
// ---------------------------------------------------------------------------

export interface UnknownYearErrorBody {
  error: 'unknown_year'
  year: number
  available_years: number[]
}

export interface AmbiguousTeamErrorBody {
  error: 'ambiguous_team'
  query: string
  candidates: string[]
}

/**
 * 404: the name resolved to no team with a rating for that exact
 * `year`/`sport` (issue #100). Split out of `ambiguous_team`, which used to
 * carry this case with an *empty* `candidates` array and therefore rendered
 * as "did you mean:" followed by nothing to pick.
 *
 * Deliberately carries **no** correction candidates. An earlier cut of this
 * body had a fuzzy-matched `suggestions` array; it was removed from the wire
 * because the engine's strict stage already resolves anything scoring >= 0.6,
 * so the only names that could ever reach this branch score below that -- and
 * at that range there is no cutoff separating signal from noise
 * ("Gonzaga"/"Georgia" scores 0.5714, above "Texas"/"Houston Texans" at
 * 0.5263). The pills would have offered real-but-irrelevant teams. This is a
 * pure not-found state: `query`, plus the `year` and `sport` scope that came
 * up empty, which is what `VerdictError`'s copy names.
 */
export interface UnknownTeamErrorBody {
  error: 'unknown_team'
  query: string
  year: number
  sport: Sport
}

export interface SameTeamComparisonErrorBody {
  error: 'same_team_comparison'
  team_name: string
}

export type VerdictErrorBody =
  | UnknownYearErrorBody
  | AmbiguousTeamErrorBody
  | UnknownTeamErrorBody
  | SameTeamComparisonErrorBody

/**
 * Discriminated union covering the four mapped HTTP error cases plus a
 * catch-all for network/unreachable-API failures -- shared by `VerdictError`
 * and `VerdictCard` so both render off the same shape.
 */
export type VerdictErrorState =
  | { kind: 'unknown_year'; body: UnknownYearErrorBody }
  | { kind: 'ambiguous_team'; body: AmbiguousTeamErrorBody }
  | { kind: 'unknown_team'; body: UnknownTeamErrorBody }
  | { kind: 'same_team_comparison'; body: SameTeamComparisonErrorBody }
  | { kind: 'network_error'; message: string }

/** The full set of states `VerdictCard` renders -- loading, success, or one of the five error cases above. */
export type VerdictCardState =
  | { status: 'loading' }
  | { status: 'success'; envelope: VerdictEnvelope }
  | { status: 'error'; error: VerdictErrorState }

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

function isSport(value: unknown): value is Sport {
  // Widened to `readonly unknown[]` so `includes` accepts an unvalidated value.
  return (SPORTS as readonly unknown[]).includes(value)
}

export function isVerdictErrorBody(value: unknown): value is VerdictErrorBody {
  if (!isRecord(value) || typeof value['error'] !== 'string') {
    return false
  }
  switch (value['error']) {
    case 'unknown_year':
      return (
        typeof value['year'] === 'number' &&
        Array.isArray(value['available_years'])
      )
    case 'ambiguous_team':
      return (
        typeof value['query'] === 'string' && Array.isArray(value['candidates'])
      )
    case 'unknown_team':
      return (
        typeof value['query'] === 'string' &&
        typeof value['year'] === 'number' &&
        isSport(value['sport'])
      )
    case 'same_team_comparison':
      return typeof value['team_name'] === 'string'
    default:
      return false
  }
}
