/**
 * Thin fetch client for `apps/api`'s `/api/verdict/*` routes. Pages call
 * into this module (or a page's own effect); components never fetch data
 * directly -- see `.dependency-cruiser.cjs` / CLAUDE.md's boundary.
 */

import type {
  ComparisonEnvelope,
  CreditsOut,
  TeamCaseEnvelope,
  VerdictErrorBody,
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
}

export interface TeamCasePayload {
  year: number
  team: string
  user_team: string | null
}

export interface ComparePayload {
  year: number
  team_a: string
  team_b: string
  user_team: string | null
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
