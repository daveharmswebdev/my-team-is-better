import type { QuestionSubmission } from '../../components/QuestionForm/QuestionForm'
import { isSport } from '../../lib/api/types'
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
 * so a link reads the same however the UI's copy changes. The format is an
 * append-only contract, pinned by literal links in `shareLink.test.ts`.
 *
 * Lives next to `HomePage` rather than in `lib/` because it depends on
 * `QuestionSubmission`, which a component owns, and `lib/` sits below
 * components.
 */

/**
 * The most characters a link's team value may have. The longest name or
 * alias in any committed catalog is 27 ("Bethel University Tennessee"), so
 * this leaves room for any real name while bounding what a link can put in
 * front of the narrator.
 */
const MAX_TEAM_NAME_LENGTH = 64

/**
 * A plain team name: Unicode letters and digits, space, and `& ' . ( ) -`.
 * Every team name and alias in the committed catalogs -- apps/api's fixture
 * db, packages/cfb-engine's cfb and nfl regression dbs, and its NFL
 * `teams.csv` -- fits it.
 */
const PLAIN_TEAM_NAME = /^[\p{L}\p{N} &'.()-]+$/u

/** A season: exactly four digits, so `Number()` is exact and never absurd. */
const FOUR_DIGIT_YEAR = /^\d{4}$/

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
  // Issue #198: the champion question has no user team, so its link never
  // carries one, whatever the submission holds.
  if (
    submission.questionType !== 'champion' &&
    submission.userTeam !== null &&
    submission.userTeam.trim() !== ''
  ) {
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
 * Since #184 a third party writes these values, and the team values reach
 * the persona's system prompt, so each (`for`, `team`, `a`, `b`) must be a
 * plain team name of at most `MAX_TEAM_NAME_LENGTH` characters. That bounds
 * what a link can inject; it is not a semantic filter.
 *
 * `engine` must be one the Engine toggle offers (`DISPLAYED_METHODS`), not
 * merely a method the API knows: the landing seeds that toggle, and a
 * hand-edited `engine=elo_career` would leave no radio checked. `year` must
 * be four digits: a longer run of digits loses precision in `Number()` past
 * 16 of them, and an absurd year made the API answer with a 500.
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
  if (
    !isSport(sport) ||
    !isDisplayedMethod(method) ||
    !FOUR_DIGIT_YEAR.test(rawYear)
  ) {
    return null
  }

  // Issue #198: the champion question has no user team. `for` on a champion
  // link -- #184 minted them -- is ignored outright, not validated, so every
  // such link still opens, and a malformed `for` can't reach the narrator
  // through it.
  if (questionType === 'champion') {
    return {
      questionType,
      year: Number(rawYear),
      userTeam: null,
      sport,
      method,
    }
  }

  const forTeam = read('for')
  if (forTeam !== '' && !isPlainTeamName(forTeam)) {
    return null
  }
  const base = {
    year: Number(rawYear),
    userTeam: forTeam === '' ? null : forTeam,
    sport,
    method,
  }

  if (questionType === 'team_case') {
    const team = read('team')
    return isPlainTeamName(team) ? { questionType, team, ...base } : null
  }
  if (questionType === 'compare') {
    const teamA = read('a')
    const teamB = read('b')
    return isPlainTeamName(teamA) && isPlainTeamName(teamB)
      ? { questionType, teamA, teamB, ...base }
      : null
  }
  return null
}

/** Non-blank (the pattern needs a character), plain, and short enough. */
function isPlainTeamName(value: string): boolean {
  return value.length <= MAX_TEAM_NAME_LENGTH && PLAIN_TEAM_NAME.test(value)
}

function isDisplayedMethod(value: string): value is DisplayedMethod {
  return (DISPLAYED_METHODS as readonly string[]).includes(value)
}
