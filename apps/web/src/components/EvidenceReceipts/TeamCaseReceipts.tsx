import type { OpponentResultOut, TeamCaseOut } from '../../lib/api/types'
import styles from './TeamCaseReceipts.module.css'

export interface TeamCaseReceiptsProps {
  evidence: TeamCaseOut
}

function GameLine({ game }: { game: OpponentResultOut }) {
  const tagClass =
    game.result === 'W' ? styles.gamelineTagW : styles.gamelineTagL
  return (
    <li className={styles.gameline}>
      <span className={`${styles.gamelineTag} ${tagClass}`}>{game.result}</span>
      <span className={styles.gamelineScore}>
        {game.team_score}-{game.opponent_score}
      </span>
      <span className={styles.gamelineOpp}>
        vs {game.opponent_name}
        {game.opponent_rank !== null ? ` (#${game.opponent_rank})` : ''}
      </span>
    </li>
  )
}

/**
 * The "receipts" for a champion/team-case verdict: record, quality wins,
 * and worst loss (PRD §3 / Architecture Brief §4.3's "show your work").
 */
export function TeamCaseReceipts({ evidence }: TeamCaseReceiptsProps) {
  return (
    <section
      aria-label={`${evidence.team_name} evidence`}
      className={styles.receipts}
    >
      <p className={styles.stats}>
        Record: {evidence.wins}-{evidence.losses} &middot; Rank #{evidence.rank}{' '}
        &middot; Rating {evidence.rating.toFixed(2)}
      </p>

      <h4 className={styles.label}>Quality wins</h4>
      {evidence.quality_wins.length > 0 ? (
        <ul className={styles.list}>
          {evidence.quality_wins.map((game) => (
            <GameLine key={game.opponent_team_id} game={game} />
          ))}
        </ul>
      ) : (
        <p className={styles.empty}>No standout quality wins.</p>
      )}

      <h4 className={styles.label}>Worst loss</h4>
      {evidence.worst_loss ? (
        <ul className={styles.list}>
          <GameLine game={evidence.worst_loss} />
        </ul>
      ) : (
        <p className={styles.empty}>No losses.</p>
      )}
    </section>
  )
}
