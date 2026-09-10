export interface GreetingProps {
  /** Name of the person (or team) to greet. */
  name: string
}

/**
 * Trivial placeholder component proving the toolchain (TS, Vitest/RTL,
 * Storybook) works end to end. Not a real feature component -- see
 * apps/web's later issues for QuestionForm/VerdictCard.
 */
export function Greeting({ name }: GreetingProps) {
  return <h1>Hello, {name}!</h1>
}
