import { formatRating } from '../../lib/formatRating'
import type {
  ComparisonResultOut,
  ComparisonTeamSummaryOut,
  CommonOpponentOut,
  HeadToHeadMeetingOut,
} from '../../lib/api/types'
import { RatingBreakdownDisclosure } from './RatingBreakdownDisclosure'
import styles from './ComparisonReceipts.module.css'

export interface ComparisonReceiptsProps {
  evidence: ComparisonResultOut
}

/**
 * `OpponentCreditOut` (each `rating_breakdown` entry) only carries a numeric
 * `opponent_team_id`, not a name -- there is no full-schedule field on this
 * response to resolve every id from. This resolves whatever names *are*
 * available elsewhere in the same evidence (both teams' `quality_wins`/
 * `worst_loss`, plus `common_opponents`) as a best effort; an id not covered
 * by any of those falls back to a visible numeric id in
 * `RatingBreakdownDisclosure` rather than a guess. See this issue's
 * `contract_gaps` for the underlying gap.
 */
function buildOpponentNameMap(
  evidence: ComparisonResultOut,
): Record<number, string> {
  const names: Record<number, string> = {}
  for (const team of [evidence.team_a, evidence.team_b]) {
    for (const game of team.quality_wins) {
      names[game.opponent_team_id] = game.opponent_name
    }
    if (team.worst_loss) {
      names[team.worst_loss.opponent_team_id] = team.worst_loss.opponent_name
    }
  }
  for (const opponent of evidence.common_opponents) {
    names[opponent.opponent_team_id] = opponent.opponent_name
  }
  return names
}

/** Per-team Record/Rating summary (design-system.html's "Comparison" mockup's `kv-grid`). */
function TeamSummary({
  team,
  opponentNames,
}: {
  team: ComparisonTeamSummaryOut
  opponentNames: Record<number, string>
}) {
  return (
    <>
      <h4 className={styles.label}>{team.team_name}</h4>
      <dl className={styles.kvGrid}>
        <div>
          <dt>Record</dt>
          <dd>
            {team.wins}-{team.losses}
          </dd>
        </div>
        <div>
          <dt>Rating</dt>
          <dd>
            <RatingBreakdownDisclosure
              teamName={team.team_name}
              rating={team.rating}
              breakdown={team.rating_breakdown}
              opponentNames={opponentNames}
            />
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

/** A common-opponent row: both teams' W/L tag and score against the shared opponent. */
function CommonOpponentLine({ opponent }: { opponent: CommonOpponentOut }) {
  const tagClassA =
    opponent.team_a_result === 'W' ? styles.gamelineTagW : styles.gamelineTagL
  const tagClassB =
    opponent.team_b_result === 'W' ? styles.gamelineTagW : styles.gamelineTagL
  return (
    <li className={styles.gameline}>
      <span className={styles.gamelineOpp}>
        vs {opponent.opponent_name}
        {opponent.opponent_rank !== null ? ` (#${opponent.opponent_rank})` : ''}
      </span>
      <span className={`${styles.gamelineTag} ${tagClassA}`}>
        {opponent.team_a_result}
      </span>
      <span>
        {opponent.team_a_score}-{opponent.team_a_opponent_score}
      </span>
      <span className={`${styles.gamelineTag} ${tagClassB}`}>
        {opponent.team_b_result}
      </span>
      <span>
        {opponent.team_b_score}-{opponent.team_b_opponent_score}
      </span>
    </li>
  )
}

/** The "receipts" for a compare verdict (PRD §3 / Architecture Brief §4.3's "show your work"). */
export function ComparisonReceipts({ evidence }: ComparisonReceiptsProps) {
  const { team_a, team_b, head_to_head, common_opponents } = evidence
  const opponentNames = buildOpponentNameMap(evidence)

  return (
    <section aria-label="comparison evidence" className={styles.receipts}>
      <TeamSummary team={team_a} opponentNames={opponentNames} />
      <TeamSummary team={team_b} opponentNames={opponentNames} />

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

      <p className={styles.verdictLine}>
        Rating diff: {formatRating(evidence.rating_diff)} &middot;{' '}
        {evidence.verdict}
      </p>
    </section>
  )
}
