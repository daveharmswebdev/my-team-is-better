import { useState } from 'react'
import type { QuestionSubmission } from '../../components/QuestionForm/QuestionForm'
import { QuestionForm } from '../../components/QuestionForm/QuestionForm'
import { VerdictCard } from '../../components/VerdictCard/VerdictCard'
import {
  VerdictApiError,
  VerdictNetworkError,
  fetchChampion,
  fetchCompare,
  fetchTeamCase,
} from '../../lib/api/client'
import type { VerdictCardState, VerdictErrorState } from '../../lib/api/types'

/**
 * Pages own composition/data-fetching; components do not import from pages
 * (enforced by dependency-cruiser -- see .dependency-cruiser.cjs).
 */
export function HomePage() {
  const [submission, setSubmission] = useState<QuestionSubmission | null>(null)
  const [state, setState] = useState<VerdictCardState | null>(null)

  async function runSubmission(next: QuestionSubmission) {
    setSubmission(next)
    setState({ status: 'loading' })
    try {
      const envelope =
        next.questionType === 'champion'
          ? await fetchChampion({ year: next.year, user_team: next.userTeam })
          : next.questionType === 'team_case'
            ? await fetchTeamCase({
                year: next.year,
                team: next.team,
                user_team: next.userTeam,
              })
            : await fetchCompare({
                year: next.year,
                team_a: next.teamA,
                team_b: next.teamB,
                user_team: next.userTeam,
              })
      setState({ status: 'success', envelope })
    } catch (error) {
      setState({ status: 'error', error: toErrorState(error) })
    }
  }

  function handleSelectYear(year: number) {
    if (!submission) {
      return
    }
    void runSubmission({ ...submission, year })
  }

  function handleSelectCandidate(candidate: string) {
    if (!submission) {
      return
    }
    if (submission.questionType === 'team_case') {
      void runSubmission({ ...submission, team: candidate })
      return
    }
    if (submission.questionType === 'compare') {
      const ambiguousQuery =
        state?.status === 'error' && state.error.kind === 'ambiguous_team'
          ? state.error.body.query
          : undefined
      void runSubmission({
        ...submission,
        teamA:
          ambiguousQuery === submission.teamA ? candidate : submission.teamA,
        teamB:
          ambiguousQuery === submission.teamB ? candidate : submission.teamB,
      })
    }
  }

  return (
    <main>
      <h1>My Team Is Better</h1>
      <QuestionForm
        onSubmit={(next) => void runSubmission(next)}
        isSubmitting={state?.status === 'loading'}
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
