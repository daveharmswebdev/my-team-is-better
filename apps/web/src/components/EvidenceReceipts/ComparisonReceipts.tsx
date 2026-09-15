import { useId } from 'react'
import { displayRatingPair, formatRating } from '../../lib/formatRating'
import { formatRecord } from '../../lib/formatRecord'
import { resultLabel } from '../../lib/resultLabel'
import type {
  ComparisonResultOut,
  ComparisonTeamSummaryOut,
  CommonOpponentMeetingOut,
  CommonOpponentOut,
  GameResult,
  HeadToHeadMeetingOut,
  Method,
} from '../../lib/api/types'
import { EloLedgerDisclosure } from './EloLedgerDisclosure'
import { RatingBreakdownDisclosure } from './RatingBreakdownDisclosure'
import {
  RATING_BREAKDOWN_BY_METHOD,
  ratingWorkFor,
} from './ratingBreakdownByMethod'
import styles from './ComparisonReceipts.module.css'

const TAG_CLASS: Record<GameResult, string | undefined> = {
  W: styles.gamelineTagW,
  L: styles.gamelineTagL,
  T: styles.gamelineTagT,
}

/**
 * One side's W/L/T pill: the visible letter is hidden from assistive tech and
 * the spoken word ("Win"/"Loss"/"Tie") is visually hidden, so a tie never
 * reads as the bare letter "T" and never relies on colour alone.
 */
function ResultTag({ result }: { result: GameResult }) {
  return (
    <span className={`${styles.gamelineTag} ${TAG_CLASS[result]}`}>
      <span aria-hidden="true">{result}</span>
      <span className={styles.visuallyHidden}>{resultLabel(result)}</span>
    </span>
  )
}

export interface ComparisonReceiptsProps {
  evidence: ComparisonResultOut
}

/** Per-team Record/Rating summary (design-system.html's "Comparison" mockup's `kv-grid`). */
function TeamSummary({
  team,
  method,
}: {
  team: ComparisonTeamSummaryOut
  method: Method
}) {
  // Issues #153/#183: by method, never by the breakdown's emptiness.
  const work = ratingWorkFor(method, team.elo_ledger)

  return (
    <>
      <h4 className={styles.label}>{team.team_name}</h4>
      <dl className={styles.kvGrid}>
        <div>
          <dt>Record</dt>
          <dd>{formatRecord(team.wins, team.losses, team.ties)}</dd>
        </div>
        <div>
          <dt>Rating</dt>
          <dd>
            {work.kind === 'keener-breakdown' ? (
              <RatingBreakdownDisclosure
                teamName={team.team_name}
                method={method}
                rating={team.rating}
                breakdown={team.rating_breakdown}
              />
            ) : work.kind === 'elo-ledger' ? (
              <EloLedgerDisclosure
                teamName={team.team_name}
                rating={team.rating}
                ledger={work.ledger}
              />
            ) : (
              formatRating(team.rating, method)
            )}
            {/* About this team's response, so beside this team's rating. */}
            {work.kind === 'ledger-unavailable' && (
              <p className={styles.ratingTeamNote}>{work.note}</p>
            )}
          </dd>
        </div>
      </dl>
    </>
  )
}

function MeetingRow({ meeting }: { meeting: HeadToHeadMeetingOut }) {
  return (
    <div>
      <dt>Result</dt>
      <dd>
        {meeting.home_team} {meeting.home_points}-{meeting.away_points}{' '}
        {meeting.away_team}
        {meeting.winner !== null ? ` (${meeting.winner} won)` : ''}
      </dd>
    </div>
  )
}

/**
 * When a common-opponent meeting happened, as a parenthetical: "(wk 8)", or
 * "(postseason)" for a bowl/playoff/title game (whose `week` restarts from 1
 * and would mislead), or nothing when the API has neither.
 */
function meetingWhen(meeting: CommonOpponentMeetingOut): string {
  if (meeting.season_type === 'postseason') return ' (postseason)'
  return meeting.week !== null ? ` (wk ${meeting.week})` : ''
}

/**
 * One side's meeting with the shared opponent: its W/L/T tag, score and week.
 * The "·" before every meeting but the first lives inside the meeting, so a
 * narrow screen wraps "· T 26-26 (wk 12)" as one unit instead of leaving the
 * dot dangling at the end of the previous line.
 */
function Meeting({
  meeting,
  separated,
}: {
  meeting: CommonOpponentMeetingOut
  separated: boolean
}) {
  return (
    <span className={styles.gamelineMeeting}>
      {separated && (
        <span aria-hidden="true" className={styles.gamelineSep}>
          ·
        </span>
      )}
      <ResultTag result={meeting.result} />
      <span>
        {meeting.team_score}-{meeting.opponent_score}
        {meetingWhen(meeting)}
      </span>
    </span>
  )
}

/**
 * One side's meetings with the shared opponent, every one of them in the API's
 * chronological order (issue #130), under that side's team name. The name is
 * the group's accessible label as well as its visible one: with one side
 * possibly listing two meetings and the other one, column position no longer
 * says whose results these are, for sighted or screen-reader users.
 */
function MeetingGroup({
  teamName,
  meetings,
}: {
  teamName: string
  meetings: CommonOpponentMeetingOut[]
}) {
  const labelId = useId()
  return (
    <span
      role="group"
      aria-labelledby={labelId}
      className={styles.gamelineSide}
    >
      <span id={labelId} className={styles.gamelineSideTeam}>
        {teamName}
      </span>
      {meetings.map((meeting, index) => (
        <Meeting
          key={meeting.game_id}
          meeting={meeting}
          separated={index > 0}
        />
      ))}
    </span>
  )
}

/** A common-opponent row: every meeting each team had with the shared opponent. */
function CommonOpponentLine({
  opponent,
  teamAName,
  teamBName,
}: {
  opponent: CommonOpponentOut
  teamAName: string
  teamBName: string
}) {
  return (
    <li className={styles.gameline}>
      <span className={styles.gamelineOpp}>
        vs {opponent.opponent_name}
        {opponent.opponent_rank !== null ? ` (#${opponent.opponent_rank})` : ''}
      </span>
      <MeetingGroup teamName={teamAName} meetings={opponent.team_a_meetings} />
      <MeetingGroup teamName={teamBName} meetings={opponent.team_b_meetings} />
    </li>
  )
}

/**
 * apps/web's own bottom line, "Rating diff: {diff} · {sentence}", built from
 * the summaries at display precision (issue #24) instead of the engine's raw
 * `verdict`, which restates head-to-head/common opponents already rendered
 * above and prints ratings at engine precision. Numbers are always ordered
 * team_a-then-team_b. When both ratings print identically (an exact tie
 * included) it names no leader: a leader beside two identical printed numbers
 * is the web half of #149's bug.
 *
 * The diff, the "same" test and the leader all come from `displayRatingPair`,
 * i.e. from the two ratings rounded once to display precision. The API's raw
 * `rating_diff` is deliberately NOT used here, even though it is right there:
 * rounded on its own it can contradict the two printed ratings (Elo `1531.5`
 * vs `1531.4` prints "Rating diff: 0" beside "1,532 vs 1,531"; `1531.49` vs
 * `1530.5` prints "Rating diff: 1" beside "rate the same (1,531)").
 */
function verdictLine({ method, team_a, team_b }: ComparisonResultOut): string {
  const {
    a: fa,
    b: fb,
    diff,
    leader,
  } = displayRatingPair(team_a.rating, team_b.rating, method)
  const ranks = `rank ${team_a.rank} vs ${team_b.rank}`
  const sentence =
    leader === null
      ? `${team_a.team_name} and ${team_b.team_name} rate the same at display precision (${fa}; ${ranks}).`
      : `${leader === 'a' ? team_a.team_name : team_b.team_name} rates higher overall (${fa} vs ${fb}, ${ranks}).`
  return `Rating diff: ${diff} · ${sentence}`
}

/** The "receipts" for a compare verdict (PRD §3 / Architecture Brief §4.3's "show your work"). */
export function ComparisonReceipts({ evidence }: ComparisonReceiptsProps) {
  const { method, team_a, team_b, head_to_head, common_opponents } = evidence
  const breakdownSupport = RATING_BREAKDOWN_BY_METHOD[method]

  return (
    <section aria-label="comparison evidence" className={styles.receipts}>
      <TeamSummary team={team_a} method={method} />
      <TeamSummary team={team_b} method={method} />
      {/* About the method, so once for the whole block, not once per team. */}
      {breakdownSupport.kind === 'no-disclosure' && (
        <p className={styles.ratingNote}>{breakdownSupport.explainer}</p>
      )}

      <h4 className={styles.label}>Head to head</h4>
      {head_to_head.played ? (
        <dl className={styles.kvGrid}>
          {head_to_head.meetings.map((meeting) => (
            <MeetingRow key={meeting.game_id} meeting={meeting} />
          ))}
        </dl>
      ) : (
        <p className={styles.empty}>
          {team_a.team_name} and {team_b.team_name} did not play each other.
        </p>
      )}

      <h4 className={styles.label}>Common opponents</h4>
      {common_opponents.length > 0 ? (
        <ul className={styles.list}>
          {common_opponents.map((opponent) => (
            <CommonOpponentLine
              key={opponent.opponent_team_id}
              opponent={opponent}
              teamAName={team_a.team_name}
              teamBName={team_b.team_name}
            />
          ))}
        </ul>
      ) : (
        <p className={styles.empty}>No common opponents.</p>
      )}

      <p className={styles.verdictLine}>{verdictLine(evidence)}</p>
    </section>
  )
}
