/**
 * The one way tests and stories fake `apps/api` (issue #221): Mock Service
 * Worker request handlers, typed against `src/lib/api/types.ts`. Vitest serves
 * them through `msw/node` (`src/test/server.ts`, wired up in
 * `src/test/setup.ts`; a test adds its own with `server.use()`), Storybook
 * through `msw-storybook-addon` (`.storybook/preview.tsx`; a story adds its
 * own under `parameters.msw.handlers`). Either way the code under test calls
 * the real `src/lib/api/client.ts`, so its URLs, error mapping, timeouts and
 * aborts are exercised too. `eslint.config.js` bans the old alternatives
 * (replacing `fetch`, `vi.mock`-ing the client).
 *
 * Each endpoint builder takes a resolver shaped like the client function that
 * calls the endpoint: it decodes the request into that function's arguments
 * (the JSON body, the query string, the path) and hands them over. So a test
 * can pass a `vi.fn()` resolver and assert what the page asked for in the
 * client's own terms, while the bytes still cross the client and the network
 * layer. A resolver answers with the response body (served as a JSON 200),
 * or with any `Response`: `typedError`, `httpError` or `networkError` below,
 * or one of MSW's own. Returning or throwing (rejecting with) a `Response`
 * both serve it; a promise that never settles is a request that hangs until
 * the client's timeout or the caller's abort.
 *
 * Paths match on any origin (`*`), since `VITE_API_BASE_URL` decides it.
 * Nothing here may import Vitest: stories import this module too.
 */
import { http, HttpResponse, type JsonBodyType } from 'msw'
import type {
  ChampionPayload,
  ComparePayload,
  PlayerLeadersQuery,
  TeamCasePayload,
} from '../lib/api/client'
import type {
  ComparisonEnvelope,
  CreditsOut,
  Method,
  PlayerCareerOut,
  PlayerComparisonOut,
  PlayerLeaderCategory,
  PlayerLeaderSort,
  PlayerLeadersOut,
  PlayerPositionGroup,
  PlayerSearchOut,
  PlayerSeasonType,
  PlayersNotComparableErrorBody,
  QbVerdictEnvelope,
  QbVerdictPayload,
  Sport,
  TeamCaseEnvelope,
  TeamsOut,
  UnknownPlayerErrorBody,
  VerdictErrorBody,
  YearsOut,
} from '../lib/api/types'

/** What a resolver answers with: the 200 body, or a whole `Response`. */
export type Reply<T> = T | Response

/** A resolver's return: a reply now, or one later. */
export type Answer<T> = Reply<T> | Promise<Reply<T>>

/** The request's own signal: it aborts when the client gives up on it. */
export interface RequestContext {
  signal: AbortSignal
}

/** The options `searchPlayers` sends, as the API receives them. */
export interface PlayerSearchRequest {
  limit: number
  group?: PlayerPositionGroup
  signal: AbortSignal
}

/**
 * A typed error body, served as FastAPI serves it: `{ detail: body }` with
 * `status` (`apps/api/src/api/errors.py`).
 */
export function typedError(
  status: number,
  body: VerdictErrorBody | UnknownPlayerErrorBody | PlayersNotComparableErrorBody,
): Response {
  return HttpResponse.json({ detail: body }, { status })
}

/** Any other non-OK response: a 5xx, a request-validation 422, a proxy page. */
export function httpError(status: number, body = ''): Response {
  return new HttpResponse(body, { status })
}

/** The API couldn't be reached: `fetch` itself rejects. */
export function networkError(): Response {
  return HttpResponse.error()
}

/** A request that never answers; the client's timeout or abort ends it. */
export function hang(): Promise<never> {
  return new Promise<never>(() => {})
}

/** A missing or malformed parameter is the client's bug: answer it with a 400. */
class BadRequest extends Error {}

function required(params: URLSearchParams, name: string): string {
  const value = params.get(name)
  if (value === null) {
    throw new BadRequest(`missing query parameter "${name}"`)
  }
  return value
}

function integer(text: string, name: string): number {
  const value = Number(text)
  if (!Number.isInteger(value)) {
    throw new BadRequest(`"${name}" is not an integer: ${text}`)
  }
  return value
}

/**
 * A copy of `response` to serve, so one `Response` can answer any number of
 * requests (a body is read once). A network error has no body to copy.
 */
function fresh(response: Response): Response {
  return response.type === 'error' ? response : response.clone()
}

async function serve<T>(answer: () => Answer<T>): Promise<Response> {
  let reply: Reply<T>
  try {
    reply = await answer()
  } catch (error) {
    if (error instanceof Response) {
      return fresh(error)
    }
    if (error instanceof BadRequest) {
      return httpError(400, `mock API: ${error.message}`)
    }
    throw error
  }
  // `T` is one of `types.ts`'s response interfaces, all JSON; MSW's
  // `JsonBodyType` can't name an interface without an index signature.
  return reply instanceof Response
    ? fresh(reply)
    : HttpResponse.json(reply as JsonBodyType)
}

/** `GET /api/years` -> `fetchYears(sport, method)`. */
export function yearsHandler(
  resolve: (sport: Sport, method: Method) => Answer<YearsOut>,
) {
  return http.get('*/api/years', ({ request }) =>
    serve(() => {
      const params = new URL(request.url).searchParams
      return resolve(
        required(params, 'sport') as Sport,
        required(params, 'method') as Method,
      )
    }),
  )
}

/**
 * `GET /api/teams` -> `fetchTeams(sport, method, year)`; no `year` is
 * `undefined`. A `year` is passed on as whatever number it reads as, integer
 * or not, so a resolver can see (and answer as the API would, with a 422) a
 * request the client should never have sent (issue #101).
 */
export function teamsHandler(
  resolve: (
    sport: Sport,
    method: Method,
    year: number | undefined,
  ) => Answer<TeamsOut>,
) {
  return http.get('*/api/teams', ({ request }) =>
    serve(() => {
      const params = new URL(request.url).searchParams
      const year = params.get('year')
      return resolve(
        required(params, 'sport') as Sport,
        required(params, 'method') as Method,
        year === null ? undefined : Number(year),
      )
    }),
  )
}

/** `GET /api/credits` -> `fetchCredits()`. */
export function creditsHandler(resolve: () => Answer<CreditsOut>) {
  return http.get('*/api/credits', () => serve(() => resolve()))
}

function verdictHandler<P, T>(
  path: string,
  resolve: (payload: P, request: RequestContext) => Answer<T>,
) {
  return http.post(`*${path}`, async ({ request }) => {
    const payload = (await request.json()) as P
    return serve(() => resolve(payload, { signal: request.signal }))
  })
}

/** `POST /api/verdict/champion` -> `fetchChampion(payload, { signal })`. */
export function championHandler(
  resolve: (
    payload: ChampionPayload,
    request: RequestContext,
  ) => Answer<TeamCaseEnvelope>,
) {
  return verdictHandler('/api/verdict/champion', resolve)
}

/** `POST /api/verdict/team-case` -> `fetchTeamCase(payload, { signal })`. */
export function teamCaseHandler(
  resolve: (
    payload: TeamCasePayload,
    request: RequestContext,
  ) => Answer<TeamCaseEnvelope>,
) {
  return verdictHandler('/api/verdict/team-case', resolve)
}

/** `POST /api/verdict/compare` -> `fetchCompare(payload, { signal })`. */
export function compareHandler(
  resolve: (
    payload: ComparePayload,
    request: RequestContext,
  ) => Answer<ComparisonEnvelope>,
) {
  return verdictHandler('/api/verdict/compare', resolve)
}

/**
 * `POST /api/players/compare/verdict` -> `fetchQbVerdict(a, b, { signal })`.
 * Its body also carries `sport`, always `nfl`; a body without it is a 400.
 */
export function qbVerdictHandler(
  resolve: (
    a: number,
    b: number,
    request: RequestContext,
  ) => Answer<QbVerdictEnvelope>,
) {
  return verdictHandler<QbVerdictPayload, QbVerdictEnvelope>(
    '/api/players/compare/verdict',
    (payload, request) => {
      if (payload.sport !== 'nfl') {
        return httpError(400, 'mock API: the QB verdict is NFL only')
      }
      return resolve(payload.a, payload.b, request)
    },
  )
}

/** Every player endpoint is NFL only; the client always sends `sport=nfl`. */
function nflParams(request: Request): URLSearchParams {
  const params = new URL(request.url).searchParams
  if (required(params, 'sport') !== 'nfl') {
    throw new BadRequest('player endpoints are NFL only')
  }
  return params
}

/** `GET /api/players/leaders` -> `fetchPlayerLeaders(query)`. */
export function playerLeadersHandler(
  resolve: (query: PlayerLeadersQuery) => Answer<PlayerLeadersOut>,
) {
  return http.get('*/api/players/leaders', ({ request }) =>
    serve(() => {
      const params = nflParams(request)
      return resolve({
        category: required(params, 'category') as PlayerLeaderCategory,
        season_type: required(params, 'season_type') as PlayerSeasonType,
        sort: required(params, 'sort') as PlayerLeaderSort,
        limit: integer(required(params, 'limit'), 'limit'),
        offset: integer(required(params, 'offset'), 'offset'),
      })
    }),
  )
}

/**
 * `GET /api/players/search` -> `searchPlayers(query, { limit, group, signal })`.
 * `group` is present only when the request sent one.
 */
export function playerSearchHandler(
  resolve: (
    query: string,
    options: PlayerSearchRequest,
  ) => Answer<PlayerSearchOut>,
) {
  return http.get('*/api/players/search', ({ request }) =>
    serve(() => {
      const params = nflParams(request)
      const group = params.get('group')
      const limit = integer(required(params, 'limit'), 'limit')
      return resolve(
        required(params, 'q'),
        group === null
          ? { limit, signal: request.signal }
          : {
              limit,
              group: group as PlayerPositionGroup,
              signal: request.signal,
            },
      )
    }),
  )
}

/** `GET /api/players/compare` -> `fetchPlayerComparison(a, b)`. */
export function playerComparisonHandler(
  resolve: (a: number, b: number) => Answer<PlayerComparisonOut>,
) {
  return http.get('*/api/players/compare', ({ request }) =>
    serve(() => {
      const params = nflParams(request)
      return resolve(
        integer(required(params, 'a'), 'a'),
        integer(required(params, 'b'), 'b'),
      )
    }),
  )
}

/**
 * `GET /api/players/:playerId` -> `fetchPlayerCareer(playerId)`. A path
 * segment that isn't an id (`leaders`, `search`, `compare`) falls through to
 * the next handler, so the order handlers are registered in doesn't matter.
 */
export function playerCareerHandler(
  resolve: (playerId: number) => Answer<PlayerCareerOut>,
) {
  return http.get('*/api/players/:playerId', ({ request, params }) => {
    const playerId = String(params['playerId'])
    if (!/^\d+$/.test(playerId)) {
      return undefined
    }
    return serve(() => {
      nflParams(request)
      return resolve(Number(playerId))
    })
  })
}
