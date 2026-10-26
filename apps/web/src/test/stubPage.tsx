/**
 * A test-only stand-in for a page: it names itself, so a route test can see
 * which page a path landed on without rendering (or fetching for) the real
 * one. Used through `vi.mock` in `App.test.tsx`.
 */
export function StubPage({ name }: { name: string }) {
  return <p data-testid="landed">{name}</p>
}
