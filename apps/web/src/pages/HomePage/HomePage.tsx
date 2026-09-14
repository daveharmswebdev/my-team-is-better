import { useEffect, useEffectEvent, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import type {
  QuestionSubmission,
  QuestionType,
} from '../../components/QuestionForm/QuestionForm'
import { QuestionForm } from '../../components/QuestionForm/QuestionForm'
import { VerdictCard } from '../../components/VerdictCard/VerdictCard'
import {
  VerdictApiError,
  VerdictNetworkError,
  fetchChampion,
  fetchCompare,
  fetchTeamCase,
} from '../../lib/api/client'
import type {
  Method,
  Sport,
  VerdictCardState,
  VerdictErrorState,
} from '../../lib/api/types'
import styles from './HomePage.module.css'
import { fromShareSearch, toShareSearch } from './shareLink'

/**
 * A correction accepted from one of `VerdictError`'s pills, pushed back into
 * `QuestionForm` (issue #38). `QuestionForm` owns its fields as internal
 * state, so re-running the API call against a corrected submission used to
 * leave the visible form disagreeing with the question that was actually
 * just asked -- showing 2026 next to a 2018 verdict. A share-link landing
 * (issue #184) seeds the form the same way, from its first mount.
 *
 * `generation` is the remount counter: it is spent as `QuestionForm`'s
 * `key`, which is React's standard way to reset a child's internal state
 * from a parent event. That is deliberately smaller than lifting every
 * field into this page, and it leaves `userTeam`'s `localStorage`-backed
 * behavior alone (the form re-reads it on mount, and it is written on every
 * keystroke, so even an unsubmitted value survives the remount).
 */
interface FormSeed {
  generation: number
  questionType: QuestionType
  sport: Sport
  /** The engine the corrected question was asked of, so the remount keeps it (issue #154). */
  method: Method
  year: number
  team?: string
  teamA?: string
  teamB?: string
  /**
   * The "your team" to mount the form with: a share link's `for` team on
   * landing (issue #184), or `undefined` -- every pill correction -- to have
   * the form re-read `localStorage` exactly as it always has. So after a
   * correction, the field shows the visitor's saved team while the question
   * keeps the link's.
   */
  userTeam: string | null | undefined
}

function seedFrom(
  submission: QuestionSubmission,
  generation: number,
  userTeam: string | null | undefined,
): FormSeed {
  const base = {
    generation,
    questionType: submission.questionType,
    sport: submission.sport,
    method: submission.method,
    year: submission.year,
    userTeam,
  }
  if (submission.questionType === 'team_case') {
    return { ...base, team: submission.team }
  }
  if (submission.questionType === 'compare') {
    return { ...base, teamA: submission.teamA, teamB: submission.teamB }
  }
  return base
}

/**
 * Pages own composition/data-fetching; components do not import from pages
 * (enforced by dependency-cruiser -- see .dependency-cruiser.cjs).
 */
export function HomePage() {
  const [searchParams, setSearchParams] = useSearchParams()
  /**
   * The question the page was opened on, if its URL is a share link (issue
   * #184). Read once, by a lazy initializer, so no later URL change -- this
   * page's own address-bar sync on every run included -- re-triggers it.
   */
  const [landing] = useState(() => fromShareSearch(searchParams.toString()))
  /** Outlives StrictMode's double effect run on mount, so a link is asked once. */
  const landedRef = useRef(false)
  const [submission, setSubmission] = useState<QuestionSubmission | null>(null)
  const [state, setState] = useState<VerdictCardState | null>(null)
  /**
   * Seeded from a share link from the start, so the form mounts once with
   * the link's question -- and its first catalog requests use the link's
   * league and engine -- rather than mounting with the defaults and being
   * remounted by the landing effect.
   */
  const [formSeed, setFormSeed] = useState<FormSeed | null>(() =>
    landing === null ? null : seedFrom(landing, 1, landing.userTeam),
  )

  async function runSubmission(next: QuestionSubmission) {
    setSubmission(next)
    setState({ status: 'loading' })
    // The address bar is always the share link of the question on screen
    // (issue #184); `replace`, so re-asking never piles up history entries.
    setSearchParams(toShareSearch(next), { replace: true })
    try {
      const envelope =
        next.questionType === 'champion'
          ? await fetchChampion({
              year: next.year,
              user_team: next.userTeam,
              sport: next.sport,
              method: next.method,
            })
          : next.questionType === 'team_case'
            ? await fetchTeamCase({
                year: next.year,
                team: next.team,
                user_team: next.userTeam,
                sport: next.sport,
                method: next.method,
              })
            : await fetchCompare({
                year: next.year,
                team_a: next.teamA,
                team_b: next.teamB,
                user_team: next.userTeam,
                sport: next.sport,
                method: next.method,
              })
      setState({ status: 'success', envelope })
    } catch (error) {
      setState({ status: 'error', error: toErrorState(error) })
    }
  }

  /** Re-asks the corrected question *and* re-seeds the visible form with it,
   * so the two can't disagree (issue #38). "Your team" is re-read from
   * `localStorage`, as it always has been. */
  function applyCorrection(corrected: QuestionSubmission) {
    setFormSeed((previous) =>
      seedFrom(corrected, (previous?.generation ?? 0) + 1, undefined),
    )
    void runSubmission(corrected)
  }

  /** A share-link landing (issue #184): the form is already seeded, so this only asks. */
  const askSharedQuestion = useEffectEvent((linked: QuestionSubmission) => {
    void runSubmission(linked)
  })

  useEffect(() => {
    if (landing === null || landedRef.current) {
      return
    }
    landedRef.current = true
    askSharedQuestion(landing)
  }, [landing])

  function handleSelectYear(year: number) {
    if (!submission) {
      return
    }
    applyCorrection({ ...submission, year })
  }

  function handleSelectCandidate(candidate: string) {
    if (!submission) {
      return
    }
    if (submission.questionType === 'team_case') {
      applyCorrection({ ...submission, team: candidate })
      return
    }
    if (submission.questionType === 'compare') {
      // Which side of the compare the pill is correcting. `ambiguous_team`
      // is now the only error kind that offers pills, and it carries the
      // offending name in `query`, so this lookup names the side to replace
      // and the other is left exactly as the user typed it.
      const rejectedQuery = rejectedTeamQuery(state)
      applyCorrection({
        ...submission,
        teamA:
          rejectedQuery === submission.teamA ? candidate : submission.teamA,
        teamB:
          rejectedQuery === submission.teamB ? candidate : submission.teamB,
      })
    }
  }

  return (
    <main className={styles.wrap}>
      <h1 className={styles.title}>My Team Is Better</h1>
      <QuestionForm
        // Remount-to-reset: the only thing that ever changes this key is an
        // accepted pill correction (a share-link landing starts at 1), so
        // ordinary typing is never disturbed.
        key={formSeed?.generation ?? 0}
        onSubmit={(next) => void runSubmission(next)}
        isSubmitting={state?.status === 'loading'}
        initialQuestionType={formSeed?.questionType}
        initialSport={formSeed?.sport}
        initialMethod={formSeed?.method}
        initialYear={formSeed?.year}
        initialTeam={formSeed?.team}
        initialTeamA={formSeed?.teamA}
        initialTeamB={formSeed?.teamB}
        initialUserTeam={formSeed?.userTeam}
      />
      {state && (
        <VerdictCard
          state={state}
          onSelectYear={handleSelectYear}
          onSelectCandidate={handleSelectCandidate}
          shareUrl={
            state.status === 'success' && submission !== null
              ? `${window.location.origin}/?${toShareSearch(submission)}`
              : undefined
          }
        />
      )}
    </main>
  )
}

/**
 * The team name a pill correction is replacing. Still needed, and still a
 * helper rather than an inline read: `ambiguous_team` remains a pill-bearing
 * error, and its `query` is the only thing that says which side of a compare
 * question the pill applies to. It no longer has to cover `unknown_team`,
 * which offers no pills at all now. `undefined` for every other state, which
 * leaves a compare submission untouched rather than guessing at a side.
 */
function rejectedTeamQuery(state: VerdictCardState | null): string | undefined {
  if (state?.status !== 'error') {
    return undefined
  }
  const { error } = state
  return error.kind === 'ambiguous_team' ? error.body.query : undefined
}

function toErrorState(error: unknown): VerdictErrorState {
  if (error instanceof VerdictApiError) {
    // Switched (rather than `{ kind: error.body.error, body: error.body }`)
    // so each branch keeps `body`'s narrowed type correlated with `kind` --
    // TypeScript can't verify that correlation across a same-shaped object
    // literal built from two separately-typed union members.
    switch (error.body.error) {
      case 'unknown_year':
        return { kind: 'unknown_year', body: error.body }
      case 'ambiguous_team':
        return { kind: 'ambiguous_team', body: error.body }
      case 'unknown_team':
        return { kind: 'unknown_team', body: error.body }
      case 'same_team_comparison':
        return { kind: 'same_team_comparison', body: error.body }
    }
  }
  if (error instanceof VerdictNetworkError) {
    return { kind: 'network_error', message: error.message }
  }
  return {
    kind: 'network_error',
    message: 'Something went wrong. Please try again.',
  }
}
