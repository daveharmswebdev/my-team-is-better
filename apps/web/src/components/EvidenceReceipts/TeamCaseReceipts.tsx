import type { OpponentResultOut, TeamCaseOut } from '../../lib/api/types'

export interface TeamCaseReceiptsProps {
  evidence: TeamCaseOut
}

function GameLine({ game }: { game: OpponentResultOut }) {
  return (
    <li>
      {game.result} {game.team_score}-{game.opponent_score} vs{' '}
      {game.opponent_name}
      {game.opponent_rank !== null ? ` (#${game.opponent_rank})` : ''}
    </li>
  )
}

/**
 * The "receipts" for a champion/team-case verdict: record, quality wins,
 * and worst loss (PRD §3 / Architecture Brief §4.3's "show your work").
 */
export function TeamCaseReceipts({ evidence }: TeamCaseReceiptsProps) {
  return (
    <section aria-label={`${evidence.team_name} evidence`}>
      <p>
        Record: {evidence.wins}-{evidence.losses} &middot; Rank #{evidence.rank}{' '}
        &middot; Rating {evidence.rating.toFixed(2)}
      </p>

      <h4>Quality wins</h4>
      {evidence.quality_wins.length > 0 ? (
        <ul>
          {evidence.quality_wins.map((game) => (
            <GameLine key={game.opponent_team_id} game={game} />
          ))}
        </ul>
      ) : (
        <p>No standout quality wins.</p>
      )}

      <h4>Worst loss</h4>
      {evidence.worst_loss ? (
        <ul>
          <GameLine game={evidence.worst_loss} />
        </ul>
      ) : (
        <p>No losses.</p>
      )}
    </section>
  )
}
