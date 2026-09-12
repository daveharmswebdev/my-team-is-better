/**
 * Thin fetch client for `apps/api`. Pages call into this module (or a
 * page's own effect) for verdict/credits data -- see `.dependency-cruiser.cjs`
 * / CLAUDE.md's components-vs-pages boundary. `fetchYears`/`fetchTeams`
 * (issue #56) are the one documented exception: `QuestionForm` (a component)
 * calls them directly to back its year/team datalists, since that data is
 * purely presentational input-shaping local to the form, not page-level
 * verdict data-fetching -- `.dependency-cruiser.cjs` does not forbid it.
 */

import type {
  ComparisonEnvelope,
  CreditsOut,
  Sport,
  TeamCaseEnvelope,
  TeamsOut,
  VerdictErrorBody,
  YearsOut,
} from './types'
import { isVerdictErrorBody } from './types'

const API_BASE_URL: string =
  (import.meta.env.VITE_API_BASE_URL as string | undefined) ??
  'http://localhost:8000'

/** A mapped 4xx error from `apps/api/src/api/errors.py` (404/422/400). */
export class VerdictApiError extends Error {
  readonly status: number
  readonly body: VerdictErrorBody

  constructor(status: number, body: VerdictErrorBody) {
    super(`verdict API error (${status}): ${body.error}`)
    this.name = 'VerdictApiError'
    this.status = status
    this.body = body
  }
}

/** Unreachable API, an unmapped error response shape, or any other non-2xx/network failure. */
export class VerdictNetworkError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'VerdictNetworkError'
  }
}

async function postVerdict<T>(path: string, payload: unknown): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
  } catch {
    throw new VerdictNetworkError(
      'Could not reach the API. Check your connection and try again.',
    )
  }

  if (!response.ok) {
    let detail: unknown
    try {
      const parsed: unknown = await response.json()
      detail = isRecord(parsed) ? parsed['detail'] : undefined
    } catch {
      detail = undefined
    }
    if (isVerdictErrorBody(detail)) {
      throw new VerdictApiError(response.status, detail)
    }
    throw new VerdictNetworkError(
      `Unexpected API error (status ${response.status}).`,
    )
  }

  return (await response.json()) as T
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

export interface ChampionPayload {
  year: number
  user_team: string | null
  sport: Sport
}

export interface TeamCasePayload {
  year: number
  team: string
  user_team: string | null
  sport: Sport
}

export interface ComparePayload {
  year: number
  team_a: string
  team_b: string
  user_team: string | null
  sport: Sport
}

export function fetchChampion(
  payload: ChampionPayload,
): Promise<TeamCaseEnvelope> {
  return postVerdict<TeamCaseEnvelope>('/api/verdict/champion', payload)
}

export function fetchTeamCase(
  payload: TeamCasePayload,
): Promise<TeamCaseEnvelope> {
  return postVerdict<TeamCaseEnvelope>('/api/verdict/team-case', payload)
}

export function fetchCompare(
  payload: ComparePayload,
): Promise<ComparisonEnvelope> {
  return postVerdict<ComparisonEnvelope>('/api/verdict/compare', payload)
}

/**
 * `GET /api/credits` for the About page -- mirrors `postVerdict`'s
 * error-handling shape (network failure and non-2xx both collapse to a
 * `VerdictNetworkError`; there's no mapped 4xx contract for this endpoint
 * the way there is for `/api/verdict/*`, so `VerdictApiError` doesn't apply
 * here).
 */
export async function fetchCredits(): Promise<CreditsOut> {
  let response: Response
  try {
    response = await fetch(`${API_BASE_URL}/api/credits`)
  } catch {
    throw new VerdictNetworkError(
      'Could not reach the API. Check your connection and try again.',
    )
  }

  if (!response.ok) {
    throw new VerdictNetworkError(
      `Unexpected API error (status ${response.status}).`,
    )
  }

  return (await response.json()) as CreditsOut
}

/**
 * Shared GET helper for `apps/api/src/api/catalog.py`'s `/api/years` and
 * `/api/teams` -- both take an optional `sport` query param (issue #59),
 * threaded through explicitly by callers here as of `QuestionForm`'s
 * College/NFL toggle (issue #60). Mirrors `fetchCredits`'s error handling:
 * any failure collapses to a `VerdictNetworkError` so `QuestionForm` can
 * degrade to unvalidated input on a catalog-fetch failure rather than
 * blocking submission.
 */
async function getCatalog<T>(path: string, sport: Sport): Promise<T> {
  let response: Response
  try {
    response = await fetch(
      `${API_BASE_URL}${path}?sport=${encodeURIComponent(sport)}`,
    )
  } catch {
    throw new VerdictNetworkError(
      'Could not reach the API. Check your connection and try again.',
    )
  }

  if (!response.ok) {
    throw new VerdictNetworkError(
      `Unexpected API error (status ${response.status}).`,
    )
  }

  return (await response.json()) as T
}

/** `GET /api/years` -- the year picker's valid-selection universe, scoped
 * to `sport` (defaults to `"cfb"`, matching `apps/api`'s own default). */
export function fetchYears(sport: Sport = 'cfb'): Promise<YearsOut> {
  return getCatalog<YearsOut>('/api/years', sport)
}

/** `GET /api/teams` -- the team picker's valid-selection universe, scoped
 * to `sport` (defaults to `"cfb"`, matching `apps/api`'s own default). */
export function fetchTeams(sport: Sport = 'cfb'): Promise<TeamsOut> {
  return getCatalog<TeamsOut>('/api/teams', sport)
}
