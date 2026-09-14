/**
 * Thin fetch client for `apps/api`. Pages call into this module (or a
 * page's own effect) for verdict/credits data -- see `.dependency-cruiser.cjs`
 * / CLAUDE.md's components-vs-pages boundary. `fetchYears`/`fetchTeams`
 * (issue #56) are the one documented exception: `QuestionForm` (a component)
 * calls them directly to back its year suggestions and its `TeamCombobox`
 * fields (issue #80), since that data is
 * purely presentational input-shaping local to the form, not page-level
 * verdict data-fetching -- `.dependency-cruiser.cjs` does not forbid it.
 *
 * Every failure a user can see carries plain copy in the narrator's voice,
 * never a raw HTTP status (issue #215):
 * - `fetch` itself rejects, or a verdict request times out: `VerdictNetworkError`.
 * - a verdict endpoint's typed error body: `VerdictApiError` (in-character copy
 *   lives in `VerdictError`).
 * - any other non-OK response: `VerdictHttpError`, whose message is chosen by
 *   status class. Its status and raw body stay on the object and in the
 *   console, for developers.
 */

import type {
  ComparisonEnvelope,
  CreditsOut,
  Method,
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

/**
 * How long a verdict request may take, headers and body together, before it
 * is abandoned as a network error (issue #214). Cold, uncached production
 * verdict calls measured 2.0-4.2 s end to end (2026-09-12..14), cache hits
 * ~0.15 s, and the API's Render plan does not spin down -- so 30 s is ~7x the
 * slowest observed, with no cold-wake to allow for.
 */
export const VERDICT_TIMEOUT_MS = 30_000

/** The API couldn't be reached, or a verdict request timed out. */
export const NETWORK_ERROR_COPY =
  "Lost you there, pal. Couldn't get through. Check your connection and ask me again."

/** An unmapped 4xx: something in the request itself didn't come through. */
export const CLIENT_ERROR_COPY =
  "Didn't catch that one, pal. Something in the question came through garbled. Check it and ask me again."

/** An unmapped 5xx, any other non-OK response, or an error nothing classified. */
export const SERVER_ERROR_COPY =
  "Hang on, something broke in the back. That's on us, not you. Give it a minute and ask me again."

/** A mapped 4xx from `apps/api/src/api/errors.py` (404/422/400). */
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

/** Unreachable API (`fetch` rejected), or a verdict request that timed out. */
export class VerdictNetworkError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'VerdictNetworkError'
  }
}

/**
 * A non-OK response that isn't a typed `VerdictErrorBody` (issue #215): a
 * FastAPI request-validation 422, any 5xx, a proxy's HTML error page. The
 * message is user-facing copy only and never contains the status or body;
 * those are kept here for developers.
 */
export class VerdictHttpError extends Error {
  readonly status: number
  /** The raw response text, or `''` if it couldn't be read. */
  readonly bodyText: string

  constructor(status: number, bodyText: string) {
    super(status >= 400 && status < 500 ? CLIENT_ERROR_COPY : SERVER_ERROR_COPY)
    this.name = 'VerdictHttpError'
    this.status = status
    this.bodyText = bodyText
  }
}

/** Options every verdict call accepts. */
export interface VerdictRequestOptions {
  /**
   * Aborts the request, e.g. when the question is superseded or dismissed.
   * The call then rejects with a `DOMException` named `AbortError`, never a
   * `VerdictNetworkError` or `VerdictHttpError`.
   */
  signal?: AbortSignal
}

function abortError(): DOMException {
  return new DOMException('The verdict request was aborted.', 'AbortError')
}

/** Builds the error for an unmapped non-OK response, logging what the user won't see. */
function unmappedHttpError(
  url: string,
  status: number,
  bodyText: string,
): VerdictHttpError {
  console.error(`[api] ${url} answered HTTP ${status}:`, bodyText)
  return new VerdictHttpError(status, bodyText)
}

/**
 * `work`, unless `signal` aborts first -- for reading a body, which a
 * response already in hand doesn't give up on by itself.
 */
async function untilAborted<T>(
  work: Promise<T>,
  signal: AbortSignal,
): Promise<T> {
  let stopListening = () => {}
  const aborted = new Promise<never>((_resolve, reject) => {
    const onAbort = () => {
      reject(abortError())
    }
    if (signal.aborted) {
      onAbort()
      return
    }
    signal.addEventListener('abort', onAbort, { once: true })
    stopListening = () => {
      signal.removeEventListener('abort', onAbort)
    }
  })
  try {
    return await Promise.race([work, aborted])
  } finally {
    stopListening()
  }
}

/** The response's raw text, `''` if it can't be read -- unless `signal` aborted. */
async function readBodyText(
  response: Response,
  signal?: AbortSignal,
): Promise<string> {
  try {
    const text = response.text()
    return await (signal === undefined ? text : untilAborted(text, signal))
  } catch (error) {
    if (signal?.aborted === true) {
      throw error
    }
    return ''
  }
}

function errorDetail(bodyText: string): unknown {
  try {
    const parsed: unknown = JSON.parse(bodyText)
    return isRecord(parsed) ? parsed['detail'] : undefined
  } catch {
    return undefined
  }
}

/**
 * One verdict request, bounded by `VERDICT_TIMEOUT_MS` from the start of the
 * request to the end of reading its body, and abortable by the caller. The
 * timer is `setTimeout` + `AbortController` rather than `AbortSignal.timeout`
 * / `AbortSignal.any`, so fake timers drive it and older mobile Safari has it.
 */
async function postVerdict<T>(
  path: string,
  payload: unknown,
  options: VerdictRequestOptions = {},
): Promise<T> {
  const callerSignal = options.signal
  const controller = new AbortController()
  const abortForCaller = () => {
    controller.abort(abortError())
  }
  if (callerSignal?.aborted === true) {
    abortForCaller()
  } else {
    callerSignal?.addEventListener('abort', abortForCaller, { once: true })
  }
  const timer = setTimeout(() => {
    controller.abort(new VerdictNetworkError(NETWORK_ERROR_COPY))
  }, VERDICT_TIMEOUT_MS)

  try {
    return await sendVerdict<T>(
      `${API_BASE_URL}${path}`,
      payload,
      controller.signal,
    )
  } catch (error) {
    if (controller.signal.aborted) {
      // Whatever the fetch or body read rejected with, the abort's reason
      // says why: the timer's network error, or the caller's abort.
      const reason: unknown = controller.signal.reason
      throw reason instanceof VerdictNetworkError ? reason : abortError()
    }
    throw error
  } finally {
    clearTimeout(timer)
    callerSignal?.removeEventListener('abort', abortForCaller)
  }
}

async function sendVerdict<T>(
  url: string,
  payload: unknown,
  signal: AbortSignal,
): Promise<T> {
  let response: Response
  try {
    response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      signal,
    })
  } catch {
    throw new VerdictNetworkError(NETWORK_ERROR_COPY)
  }

  if (!response.ok) {
    // Read once as text, so the raw body survives even when it isn't JSON.
    const bodyText = await readBodyText(response, signal)
    const detail = errorDetail(bodyText)
    if (isVerdictErrorBody(detail)) {
      throw new VerdictApiError(response.status, detail)
    }
    throw unmappedHttpError(url, response.status, bodyText)
  }

  return await untilAborted(response.json() as Promise<T>, signal)
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

/**
 * Every verdict payload carries the rating `method` the Engine toggle selected
 * (issue #154). Required rather than optional, so a caller can't silently fall
 * back to the API's `keener` default while the form shows Elo.
 */
export interface ChampionPayload {
  year: number
  user_team: string | null
  sport: Sport
  method: Method
}

export interface TeamCasePayload {
  year: number
  team: string
  user_team: string | null
  sport: Sport
  method: Method
}

export interface ComparePayload {
  year: number
  team_a: string
  team_b: string
  user_team: string | null
  sport: Sport
  method: Method
}

export function fetchChampion(
  payload: ChampionPayload,
  options?: VerdictRequestOptions,
): Promise<TeamCaseEnvelope> {
  return postVerdict<TeamCaseEnvelope>(
    '/api/verdict/champion',
    payload,
    options,
  )
}

export function fetchTeamCase(
  payload: TeamCasePayload,
  options?: VerdictRequestOptions,
): Promise<TeamCaseEnvelope> {
  return postVerdict<TeamCaseEnvelope>(
    '/api/verdict/team-case',
    payload,
    options,
  )
}

export function fetchCompare(
  payload: ComparePayload,
  options?: VerdictRequestOptions,
): Promise<ComparisonEnvelope> {
  return postVerdict<ComparisonEnvelope>(
    '/api/verdict/compare',
    payload,
    options,
  )
}

/**
 * Shared GET for the endpoints with no typed error contract: a rejected
 * `fetch` is a `VerdictNetworkError`, and any non-OK response a
 * `VerdictHttpError`. No timeout here (issue #214 scoped it to verdicts).
 */
async function getJson<T>(url: string): Promise<T> {
  let response: Response
  try {
    response = await fetch(url)
  } catch {
    throw new VerdictNetworkError(NETWORK_ERROR_COPY)
  }

  if (!response.ok) {
    throw unmappedHttpError(url, response.status, await readBodyText(response))
  }

  return (await response.json()) as T
}

/**
 * `GET /api/credits` for the About page. There's no mapped 4xx contract for
 * this endpoint the way there is for `/api/verdict/*`, so `VerdictApiError`
 * doesn't apply: see `getJson`.
 */
export function fetchCredits(): Promise<CreditsOut> {
  return getJson<CreditsOut>(`${API_BASE_URL}/api/credits`)
}

/**
 * Shared GET helper for `apps/api/src/api/catalog.py`'s `/api/years` and
 * `/api/teams` -- both take an optional `sport` query param (issue #59),
 * threaded through explicitly by callers here as of `QuestionForm`'s
 * College/NFL toggle (issue #60), and `/api/teams` additionally takes an
 * optional `year` (issue #78). `params` is built by the caller so each
 * endpoint sends exactly the params it supports and nothing else --
 * `/api/years` still sends `?sport=...` alone. Errors are `getJson`'s;
 * `QuestionForm` degrades to unvalidated input on any of them rather than
 * blocking submission.
 */
function getCatalog<T>(
  path: string,
  params: Record<string, string>,
): Promise<T> {
  const query = new URLSearchParams(params).toString()
  return getJson<T>(`${API_BASE_URL}${path}?${query}`)
}

/** `GET /api/years` -- the year picker's valid-selection universe, scoped
 * to `sport` and rating `method` (defaulting to `"cfb"`/`"keener"`, matching
 * `apps/api`'s own defaults): a season only has data for the engine that
 * actually rated it (issue #154). Deliberately sends `sport` and `method` and
 * nothing else: `/api/years` is not year-scoped (issue #78). */
export function fetchYears(
  sport: Sport = 'cfb',
  method: Method = 'keener',
): Promise<YearsOut> {
  return getCatalog<YearsOut>('/api/years', { sport, method })
}

/**
 * `GET /api/teams` -- the team picker's valid-selection universe, scoped to
 * `sport` and rating `method` (defaulting to `"cfb"`/`"keener"`, matching
 * `apps/api`'s own defaults; issue #154) and, when given, to `year`.
 *
 * An omitted or non-integer `year` (`NaN`, `Infinity`, `2018.5`) sends **no**
 * `year` param rather than a placeholder: `apps/api` then returns the full
 * per-sport list, which is the right pre-selection state. Sending a
 * non-integer would be worse than useless -- `/api/teams` declares `year` an
 * `int`, so `2018.5` is a 422 (issue #101). (`Number('')` is `0`, an integer,
 * so callers must resolve an empty year input to `undefined` themselves, and
 * screen implausible magnitudes -- `QuestionForm.parseYear` does both.)
 */
export function fetchTeams(
  sport: Sport = 'cfb',
  method: Method = 'keener',
  year?: number,
): Promise<TeamsOut> {
  const params: Record<string, string> =
    year !== undefined && Number.isInteger(year)
      ? { sport, method, year: String(year) }
      : { sport, method }
  return getCatalog<TeamsOut>('/api/teams', params)
}
