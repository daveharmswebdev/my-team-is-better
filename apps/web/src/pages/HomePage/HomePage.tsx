import { useState } from 'react'
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
  Sport,
  VerdictCardState,
  VerdictErrorState,
} from '../../lib/api/types'
import styles from './HomePage.module.css'

/**
 * A correction accepted from one of `VerdictError`'s pills, pushed back into
 * `QuestionForm` (issue #38). `QuestionForm` owns its fields as internal
 * state, so re-running the API call against a corrected submission used to
 * leave the visible form disagreeing with the question that was actually
 * just asked -- showing 2026 next to a 2018 verdict.
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
  year: number
  team?: string
  teamA?: string
  teamB?: string
}

function seedFrom(
  submission: QuestionSubmission,
  generation: number,
): FormSeed {
  const base = {
    generation,
    questionType: submission.questionType,
    sport: submission.sport,
    year: submission.year,
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
  const [submission, setSubmission] = useState<QuestionSubmission | null>(null)
  const [state, setState] = useState<VerdictCardState | null>(null)
  const [formSeed, setFormSeed] = useState<FormSeed | null>(null)

  async function runSubmission(next: QuestionSubmission) {
    setSubmission(next)
    setState({ status: 'loading' })
    try {
      const envelope =
        next.questionType === 'champion'
          ? await fetchChampion({
              year: next.year,
              user_team: next.userTeam,
              sport: next.sport,
            })
          : next.questionType === 'team_case'
            ? await fetchTeamCase({
                year: next.year,
                team: next.team,
                user_team: next.userTeam,
                sport: next.sport,
              })
            : await fetchCompare({
                year: next.year,
                team_a: next.teamA,
                team_b: next.teamB,
                user_team: next.userTeam,
                sport: next.sport,
              })
      setState({ status: 'success', envelope })
    } catch (error) {
      setState({ status: 'error', error: toErrorState(error) })
    }
  }

  /** Re-asks the corrected question *and* re-seeds the visible form with it,
   * so the two can't disagree (issue #38). */
  function applyCorrection(corrected: QuestionSubmission) {
    setFormSeed((previous) =>
      seedFrom(corrected, (previous?.generation ?? 0) + 1),
    )
    void runSubmission(corrected)
  }

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
      const ambiguousQuery =
        state?.status === 'error' && state.error.kind === 'ambiguous_team'
          ? state.error.body.query
          : undefined
      applyCorrection({
        ...submission,
        teamA:
          ambiguousQuery === submission.teamA ? candidate : submission.teamA,
        teamB:
          ambiguousQuery === submission.teamB ? candidate : submission.teamB,
      })
    }
  }

  return (
    <main className={styles.wrap}>
      <h1 className={styles.title}>My Team Is Better</h1>
      <QuestionForm
        // Remount-to-reset: the only thing that ever changes this key is an
        // accepted pill correction, so ordinary typing is never disturbed.
        key={formSeed?.generation ?? 0}
        onSubmit={(next) => void runSubmission(next)}
        isSubmitting={state?.status === 'loading'}
        initialQuestionType={formSeed?.questionType}
        initialSport={formSeed?.sport}
        initialYear={formSeed?.year}
        initialTeam={formSeed?.team}
        initialTeamA={formSeed?.teamA}
        initialTeamB={formSeed?.teamB}
      />
      {state && (
        <VerdictCard
          state={state}
          onSelectYear={handleSelectYear}
          onSelectCandidate={handleSelectCandidate}
        />
      )}
    </main>
  )
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
