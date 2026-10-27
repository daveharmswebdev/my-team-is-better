import { http } from 'msw'
import { server } from './server'

/**
 * What a request carried, in `fetch`'s own terms: the client's unit tests
 * assert on exactly what it sent (issue #221).
 */
export interface SentInit {
  method: string
  headers: Headers
  /** The request body as text; `undefined` for a GET. */
  body: string | undefined
  /** The request's signal: aborted when the client gives up on it. */
  signal: AbortSignal
}

/**
 * For `src/lib/api/*.test.ts`, which test the client at the `fetch` level
 * (URLs, bodies, signals, timeouts): answers *every* request through MSW
 * with `network(url, init)`, which is usually a `vi.fn()` the test then
 * inspects the way it would a `fetch` mock. The client's real `fetch` makes
 * the request; nothing replaces it.
 *
 * `network` answers with a `Response` (resolved, returned or rejected with);
 * `networkError()` from `src/mocks/handlers.ts` makes `fetch` itself reject,
 * and a promise that never settles is a request that hangs until it's
 * aborted. A `Response` may answer several requests: each gets a copy.
 * Page and component tests use the typed endpoint handlers instead.
 */
export function answerEveryRequest(
  network: (url: string, init: SentInit) => unknown,
): void {
  server.use(
    http.all('*', async ({ request }) => {
      const body =
        request.method === 'GET' || request.method === 'HEAD'
          ? undefined
          : await request.text()
      let reply: unknown
      try {
        reply = await network(request.url, {
          method: request.method,
          headers: request.headers,
          body,
          signal: request.signal,
        })
      } catch (error) {
        reply = error
      }
      if (!(reply instanceof Response)) {
        throw new Error(
          `answerEveryRequest: ${request.method} ${request.url} was answered with ${String(reply)}, not a Response`,
        )
      }
      return reply.type === 'error' ? reply : reply.clone()
    }),
  )
}

/**
 * A 200 whose headers arrive but whose JSON body never finishes: only the
 * client's timeout or its caller's abort ends the read.
 */
export function stalledBody(): Response {
  return new Response(new ReadableStream({ start() {} }), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })
}
