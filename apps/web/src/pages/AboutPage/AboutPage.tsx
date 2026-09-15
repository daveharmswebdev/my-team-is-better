import { useEffect, useState } from 'react'
import {
  SERVER_ERROR_COPY,
  VerdictHttpError,
  VerdictNetworkError,
  fetchCredits,
} from '../../lib/api/client'
import type { CreditsOut } from '../../lib/api/types'
import styles from './AboutPage.module.css'

type CreditsState =
  | { status: 'loading' }
  | { status: 'success'; credits: CreditsOut }
  | { status: 'error'; message: string }

/**
 * The element id a location hash names. A fragment that is not valid
 * percent-encoding (`#100%`) makes `decodeURIComponent` throw, and an
 * uncaught error in an effect unmounts the page (there is no error boundary),
 * so such a hash is taken literally instead and simply names nothing.
 */
function fragmentId(hash: string): string {
  const raw = hash.slice(1)
  try {
    return decodeURIComponent(raw)
  } catch {
    return raw
  }
}

/**
 * The site's "How this works / Credits" surface -- PRD §5.6 requires this be
 * visible, not just documented, and requires the methodology citations and
 * data-source attribution be plain-language and prominent. Every word of
 * that attribution copy -- names, summaries, citations -- comes from the
 * engine's `evidence/credits.py` via `/api/credits` so the About page, the
 * API and the MCP resource cannot drift (ARCHITECTURE §4.5); none of it is
 * re-hardcoded here.
 * Pages own composition/data-fetching; components do not import from pages
 * (enforced by dependency-cruiser -- see .dependency-cruiser.cjs).
 */
export function AboutPage() {
  const [state, setState] = useState<CreditsState>({ status: 'loading' })

  useEffect(() => {
    let cancelled = false
    fetchCredits()
      .then((credits) => {
        if (!cancelled) {
          setState({ status: 'success', credits })
        }
      })
      .catch((error: unknown) => {
        if (cancelled) {
          return
        }
        // Both carry plain user-facing copy, never a raw status (issue #215).
        const message =
          error instanceof VerdictNetworkError ||
          error instanceof VerdictHttpError
            ? error.message
            : SERVER_ERROR_COPY
        setState({ status: 'error', message })
      })
    return () => {
      cancelled = true
    }
  }, [])

  // Issue #227: a link like `/about#elo` (the Elo ledger's provenance line)
  // has to land on that article. Neither the browser nor React Router can do
  // it: the browser only scrolls to a hash on a full page load, and even
  // then the method articles don't exist until the credits resolve; a
  // client-side `<Link>` never scrolls at all. So once the credits are on
  // the page, scroll to whatever `window.location.hash` names (read from
  // `window`, not the router, so the page also renders outside one).
  // `scrollIntoView` is feature-detected because jsdom lacks it.
  useEffect(() => {
    if (state.status !== 'success') {
      return
    }
    const hash = window.location.hash
    if (hash.length < 2) {
      return
    }
    const target = document.getElementById(fragmentId(hash))
    if (target !== null && typeof target.scrollIntoView === 'function') {
      target.scrollIntoView()
    }
  }, [state.status])

  return (
    <main className={styles.wrap}>
      <h1 className={styles.title}>How This Works</h1>
      <p className={styles.lede}>
        Your buddy at the end of the bar is sure his team is better. So are you.
        This is where the math actually gets checked.
      </p>

      <section className={styles.section}>
        <h2 className={styles.heading}>Why this exists</h2>
        <p className={styles.body}>
          Fandom doesn&rsquo;t need a reason &mdash; you root for your team
          because it&rsquo;s your team, and that&rsquo;s fine. This site
          isn&rsquo;t here to talk you out of that. It&rsquo;s here for the
          moment an argument needs something besides vibes: a periodic reality
          check, backed by real game results and a real algorithm, you can pull
          out next time someone says their team is &ldquo;clearly&rdquo; better.
          Sometimes the math agrees with you. Sometimes it doesn&rsquo;t. Either
          way, now you know.
        </p>
      </section>

      <section id="methods" className={styles.section}>
        <h2 className={styles.heading}>The Methods</h2>
        {state.status === 'loading' && (
          <p role="status" className={styles.loading}>
            Loading methods&hellip;
          </p>
        )}
        {state.status === 'error' && (
          <p role="alert" className={styles.error}>
            {state.message}
          </p>
        )}
        {state.status === 'success' && (
          <div className={styles.methods}>
            {/*
              Rendered in the order the API sends them -- Keener's method
              first as the validated default, Elo second as the second
              opinion -- and never sorted. Both the React key and the
              element id are `methods[0]` (issue #144): the engine checks it
              is unique across credits, and unlike the display name it is a
              stable identifier, so `/about#elo` (the Elo ledger's
              provenance link, issue #227) and `/about#keener` survive a
              rename.
            */}
            {state.credits.methodologies.map((methodology) => (
              <article
                id={methodology.methods[0]}
                className={styles.method}
                key={methodology.methods[0]}
              >
                <h3 className={styles.methodName}>{methodology.name}</h3>
                <p className={styles.body}>{methodology.summary}</p>
                <p className={styles.citation}>
                  <a href={methodology.url} target="_blank" rel="noreferrer">
                    {methodology.citation}
                  </a>
                </p>
              </article>
            ))}
          </div>
        )}
      </section>

      <section className={styles.section}>
        <h2 className={styles.heading}>The Data</h2>
        {state.status === 'loading' && (
          <p className={styles.loading}>Loading source&hellip;</p>
        )}
        {state.status === 'error' && (
          <p className={styles.error}>{state.message}</p>
        )}
        {state.status === 'success' &&
          state.credits.data_sources.map((source) => (
            <p className={styles.body} key={source.url}>
              Every game result behind these rankings comes from{' '}
              <a href={source.url} target="_blank" rel="noreferrer">
                {source.name}
              </a>
              . {source.note}
            </p>
          ))}
      </section>
    </main>
  )
}
