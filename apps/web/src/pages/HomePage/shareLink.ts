import type { QuestionSubmission } from '../../components/QuestionForm/QuestionForm'
import { SPORTS } from '../../lib/api/types'
import type { Sport } from '../../lib/api/types'
import { DISPLAYED_METHODS } from '../../lib/methods'
import type { DisplayedMethod } from '../../lib/methods'

/**
 * A verdict's share link (issue #184). The link holds the *question*, never
 * the answer: opening it re-asks the API, so a shared verdict is always the
 * one the engines give today, and there is nothing server-side to store.
 *
 * Param names are short and stable because they are public once a link has
 * been sent: `q` (question type), `sport`, `year`, `engine` (the submission's
 * `method`), `team` (team_case), `a` / `b` (compare) and `for` (the optional
 * "your team"). Values are wire values -- `engine=elo`, not a display label --
 * so a link reads the same however the UI's copy changes.
 *
 * Lives next to `HomePage` rather than in `lib/` because it depends on
 * `QuestionSubmission`, which a component owns, and `lib/` sits below
 * components.
 */

/** The share link's query string for `submission`, with no leading `?`. */
export function toShareSearch(submission: QuestionSubmission): string {
  const params = new URLSearchParams()
  params.set('q', submission.questionType)
  params.set('sport', submission.sport)
  params.set('year', String(submission.year))
  params.set('engine', submission.method)
  if (submission.questionType === 'team_case') {
    params.set('team', submission.team)
  } else if (submission.questionType === 'compare') {
    params.set('a', submission.teamA)
    params.set('b', submission.teamB)
  }
  if (submission.userTeam !== null && submission.userTeam.trim() !== '') {
    params.set('for', submission.userTeam)
  }
  return params.toString()
}

/**
 * The submission a share link's query string describes, or `null` when any
 * part of it is malformed. All or nothing on purpose: a link that half-parses
 * would silently ask a different question than the one that was shared, and a
 * plain empty home page is the honest answer to a mangled link.
 *
 * `engine` must be one the Engine toggle offers (`DISPLAYED_METHODS`), not
 * merely a method the API knows: the landing seeds that toggle, and a
 * hand-edited `engine=elo_career` would leave no radio checked.
 *
 * Accepts a leading `?`, as `location.search` has one.
 */
export function fromShareSearch(search: string): QuestionSubmission | null {
  const params = new URLSearchParams(search)
  const read = (key: string): string => (params.get(key) ?? '').trim()

  const questionType = read('q')
  const sport = read('sport')
  const method = read('engine')
  const rawYear = read('year')
  if (!isSport(sport) || !isDisplayedMethod(method) || !/^\d+$/.test(rawYear)) {
    return null
  }
  const year = Number(rawYear)
  const forTeam = read('for')
  const base = {
    year,
    userTeam: forTeam === '' ? null : forTeam,
    sport,
    method,
  }

  if (questionType === 'champion') {
    return { questionType, ...base }
  }
  if (questionType === 'team_case') {
    const team = read('team')
    return team === '' ? null : { questionType, team, ...base }
  }
  if (questionType === 'compare') {
    const teamA = read('a')
    const teamB = read('b')
    return teamA === '' || teamB === ''
      ? null
      : { questionType, teamA, teamB, ...base }
  }
  return null
}

function isSport(value: string): value is Sport {
  return (SPORTS as readonly string[]).includes(value)
}

function isDisplayedMethod(value: string): value is DisplayedMethod {
  return (DISPLAYED_METHODS as readonly string[]).includes(value)
}
