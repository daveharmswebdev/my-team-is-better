import { useEffect, useState } from 'react'
import { VerdictNetworkError, fetchCredits } from '../../lib/api/client'
import type { CreditsOut } from '../../lib/api/types'
import styles from './AboutPage.module.css'

type CreditsState =
  | { status: 'loading' }
  | { status: 'success'; credits: CreditsOut }
  | { status: 'error'; message: string }

/**
 * The site's "How this works / Credits" surface -- PRD §5.6 requires this be
 * visible, not just documented, and requires the Keener citation and
 * CollegeFootballData.com attribution be plain-language and prominent.
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
        const message =
          error instanceof VerdictNetworkError
            ? error.message
            : 'Something went wrong. Please try again.'
        setState({ status: 'error', message })
      })
    return () => {
      cancelled = true
    }
  }, [])

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

      <section className={styles.section}>
        <h2 className={styles.heading}>
          The Method &mdash; Keener&rsquo;s Ranking
        </h2>
        <p className={styles.body}>
          Every ranking on this site comes from Keener&rsquo;s method: a
          team&rsquo;s rating depends on the strength of the teams it beat,
          whose strength depends on the strength of the teams <em>they</em>{' '}
          beat, and so on &mdash; the same eigenvector idea behind
          Google&rsquo;s PageRank, applied to a season of wins and losses
          instead of web links. Win/loss is the dominant signal; margin of
          victory isn&rsquo;t weighted, so running up the score doesn&rsquo;t
          move the needle.
        </p>
        {state.status === 'loading' && (
          <p role="status" className={styles.loading}>
            Loading citation&hellip;
          </p>
        )}
        {state.status === 'error' && (
          <p role="alert" className={styles.error}>
            {state.message}
          </p>
        )}
        {state.status === 'success' && (
          <p className={styles.citation}>
            <a
              href={state.credits.methodology.url}
              target="_blank"
              rel="noreferrer"
            >
              {state.credits.methodology.citation}
            </a>
          </p>
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
        {state.status === 'success' && (
          <p className={styles.body}>
            Every game result behind these rankings comes from{' '}
            <a
              href={state.credits.data_source.url}
              target="_blank"
              rel="noreferrer"
            >
              {state.credits.data_source.name}
            </a>
            . {state.credits.data_source.note}
          </p>
        )}
      </section>
    </main>
  )
}
