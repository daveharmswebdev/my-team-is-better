import { displayRatingPair, formatRating } from '../../lib/formatRating'
import { formatRecord } from '../../lib/formatRecord'
import { resultLabel } from '../../lib/resultLabel'
import type {
  ComparisonResultOut,
  ComparisonTeamSummaryOut,
  CommonOpponentOut,
  GameResult,
  HeadToHeadMeetingOut,
  Method,
} from '../../lib/api/types'
import { RatingBreakdownDisclosure } from './RatingBreakdownDisclosure'
import { RATING_BREAKDOWN_BY_METHOD } from './ratingBreakdownByMethod'
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
            {/* Issue #153: by method, never by the breakdown's emptiness. */}
            {RATING_BREAKDOWN_BY_METHOD[method].hasBreakdown ? (
              <RatingBreakdownDisclosure
                teamName={team.team_name}
                method={method}
                rating={team.rating}
                breakdown={team.rating_breakdown}
              />
            ) : (
              formatRating(team.rating, method)
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

/** A common-opponent row: both teams' W/L/T tag and score against the shared opponent. */
function CommonOpponentLine({ opponent }: { opponent: CommonOpponentOut }) {
  return (
    <li className={styles.gameline}>
      <span className={styles.gamelineOpp}>
        vs {opponent.opponent_name}
        {opponent.opponent_rank !== null ? ` (#${opponent.opponent_rank})` : ''}
      </span>
      <ResultTag result={opponent.team_a_result} />
      <span>
        {opponent.team_a_score}-{opponent.team_a_opponent_score}
      </span>
      <ResultTag result={opponent.team_b_result} />
      <span>
        {opponent.team_b_score}-{opponent.team_b_opponent_score}
      </span>
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
      {/* Once for the whole block, not once per team. */}
      {!breakdownSupport.hasBreakdown && (
        <p className={styles.ratingNote}>{breakdownSupport.explainer}</p>
      )}

      <h4 className={styles.label}>Head to head</h4>
      {head_to_head.played ? (
        <dl className={styles.kvGrid}>
          {head_to_head.meetings.map((meeting, index) => (
            // Index-as-key: meetings have no stable id and the list is
            // render-only.
            <MeetingRow key={index} meeting={meeting} />
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
