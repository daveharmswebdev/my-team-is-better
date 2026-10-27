import { setupServer } from 'msw/node'

/**
 * The Vitest side of the MSW fake API (issue #221; handlers in
 * `src/mocks/handlers.ts`). `src/test/setup.ts` starts it before every test
 * file, resets it after every test, and fails any request no handler
 * answers. A test registers the endpoints it needs with `server.use()`.
 */
export const server = setupServer()
