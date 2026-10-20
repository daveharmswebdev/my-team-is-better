import { Component, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import styles from './RouteErrorBoundary.module.css'

/** The fallback's heading, in the bar-stool narrator's voice (issue #268). */
export const ROUTE_ERROR_HEADING = 'Fumbled that one.'

/**
 * The fallback's body. Same voice as the network/server lines in
 * `lib/api/client.ts`: never a stack trace, a raw error message or neutral
 * system text.
 */
export const ROUTE_ERROR_COPY =
  "Hang on, pal, this page fell apart on me. That's on us, not you. Pick somewhere else up top, or head back to the start and ask me again."

export type RouteErrorBoundaryProps = {
  children: ReactNode
  /**
   * Changes on every navigation (AppShell passes `location.key`). A new key
   * clears a caught error, so the next page renders normally.
   */
  resetKey: string
}

type RouteErrorBoundaryState = {
  hasError: boolean
  resetKey: string
}

/**
 * Route-level error boundary (issue #268). React 19 unmounts the whole root
 * on an uncaught render or effect error; AppShell wraps its `<Outlet />` in
 * this so a throwing page shows the narrator's fallback instead, while the
 * header and nav stay rendered and usable. React itself still logs the
 * caught error to the console; this adds no reporting of its own.
 */
export class RouteErrorBoundary extends Component<
  RouteErrorBoundaryProps,
  RouteErrorBoundaryState
> {
  constructor(props: RouteErrorBoundaryProps) {
    super(props)
    this.state = { hasError: false, resetKey: props.resetKey }
  }

  static getDerivedStateFromError(): Partial<RouteErrorBoundaryState> {
    return { hasError: true }
  }

  static getDerivedStateFromProps(
    props: RouteErrorBoundaryProps,
    state: RouteErrorBoundaryState,
  ): Partial<RouteErrorBoundaryState> | null {
    if (props.resetKey !== state.resetKey) {
      return { hasError: false, resetKey: props.resetKey }
    }
    return null
  }

  override render() {
    if (!this.state.hasError) {
      return this.props.children
    }
    return (
      <main className={styles.wrap}>
        <div role="alert" className={styles.card}>
          <h1 className={styles.heading}>{ROUTE_ERROR_HEADING}</h1>
          <p className={styles.body}>{ROUTE_ERROR_COPY}</p>
          <Link to="/" className={styles.link}>
            Back to the start
          </Link>
        </div>
      </main>
    )
  }
}
