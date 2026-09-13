import { useId } from 'react'
import type {
  GameResult,
  OpponentResultOut,
  TeamCaseOut,
} from '../../lib/api/types'
import { formatRecord } from '../../lib/formatRecord'
import { resultLabel } from '../../lib/resultLabel'
import { RatingBreakdownDisclosure } from './RatingBreakdownDisclosure'
import styles from './TeamCaseReceipts.module.css'

const TAG_CLASS: Record<GameResult, string | undefined> = {
  W: styles.gamelineTagW,
  L: styles.gamelineTagL,
  T: styles.gamelineTagT,
}

export interface TeamCaseReceiptsProps {
  evidence: TeamCaseOut
}

type Highlight = 'Quality win' | 'Worst loss'

/**
 * Identifies a specific game instance (not just an opponent) so a rematch
 * against the same team in one season -- e.g. a regular-season game and a
 * conference-championship rematch -- is treated as two distinct games when
 * cross-referencing `quality_wins`/`worst_loss` against the full schedule.
 */
function gameKey(game: OpponentResultOut): string {
  return `${game.opponent_team_id}-${game.week ?? 'na'}-${game.season_type}`
}

function GameLine({
  game,
  highlight,
}: {
  game: OpponentResultOut
  highlight?: Highlight
}) {
  return (
    <li className={styles.gameline}>
      {/* Visible letter is hidden from assistive tech; the spoken word
          ("Win"/"Loss"/"Tie") is visually hidden -- so a tie never reads as
          the bare letter "T" and never relies on colour alone. */}
      <span className={`${styles.gamelineTag} ${TAG_CLASS[game.result]}`}>
        <span aria-hidden="true">{game.result}</span>
        <span className={styles.visuallyHidden}>
          {resultLabel(game.result)}
        </span>
      </span>
      <span className={styles.gamelineScore}>
        {game.team_score}-{game.opponent_score}
      </span>
      <span className={styles.gamelineOpp}>
        vs {game.opponent_name}
        {game.opponent_rank !== null ? ` (#${game.opponent_rank})` : ''}
      </span>
      {highlight ? (
        <span className={styles.gamelineBadge}>&#9733; {highlight}</span>
      ) : null}
    </li>
  )
}

/**
 * Chronological order for a fan scanning the full season: regular-season
 * games first (by week), then postseason/bowl games -- mirrors the
 * `CASE season_type WHEN 'regular' THEN 0 ELSE 1 END, week` ordering already
 * used server-side (packages/cfb-engine's evidence/proof.py), since upstream
 * data numbers postseason weeks independently of the regular season (a bowl
 * game can carry the same `week` as an early-season game).
 */
function bySeasonOrder(a: OpponentResultOut, b: OpponentResultOut): number {
  const seasonRank = (game: OpponentResultOut) =>
    game.season_type === 'regular' ? 0 : 1
  const seasonDiff = seasonRank(a) - seasonRank(b)
  if (seasonDiff !== 0) {
    return seasonDiff
  }
  return (a.week ?? 0) - (b.week ?? 0)
}

/**
 * The "receipts" for a champion/team-case verdict: record, quality wins,
 * worst loss, and the full season schedule (PRD §3 / Architecture Brief
 * §4.3's "show your work") -- the full schedule lets a fan cross-check any
 * game the narration mentions against a real table, not just the curated
 * quality-wins/worst-loss subset.
 *
 * In production `evidence.games` is a superset of `quality_wins`/
 * `worst_loss` -- every quality win and the worst loss also shows up in the
 * full schedule. Rather than hide or dedupe those rows (which would make the
 * schedule look incomplete -- a fan scanning it should see every game the
 * team actually played), the matching full-schedule row is starred with the
 * same label so it reads as "this is that quality win/worst loss, in its
 * chronological place" rather than an unexplained duplicate.
 */
export function TeamCaseReceipts({ evidence }: TeamCaseReceiptsProps) {
  const orderedGames = [...evidence.games].sort(bySeasonOrder)

  const highlightByGame = new Map<string, Highlight>()
  for (const game of evidence.quality_wins) {
    highlightByGame.set(gameKey(game), 'Quality win')
  }
  if (evidence.worst_loss) {
    highlightByGame.set(gameKey(evidence.worst_loss), 'Worst loss')
  }

  const headingId = useId()
  const qualityWinsHeadingId = `${headingId}-quality-wins`
  const worstLossHeadingId = `${headingId}-worst-loss`
  const fullScheduleHeadingId = `${headingId}-full-schedule`

  return (
    <section
      aria-label={`${evidence.team_name} evidence`}
      className={styles.receipts}
    >
      <div className={styles.stats}>
        Record: {formatRecord(evidence.wins, evidence.losses, evidence.ties)}{' '}
        &middot; Rank #{evidence.rank} &middot; Rating{' '}
        <RatingBreakdownDisclosure
          teamName={evidence.team_name}
          rating={evidence.rating}
          breakdown={evidence.rating_breakdown}
        />
      </div>

      <h4 id={qualityWinsHeadingId} className={styles.label}>
        Quality wins
      </h4>
      {evidence.quality_wins.length > 0 ? (
        <ul className={styles.list} aria-labelledby={qualityWinsHeadingId}>
          {evidence.quality_wins.map((game) => (
            <GameLine key={game.opponent_team_id} game={game} />
          ))}
        </ul>
      ) : (
        <p className={styles.empty}>No standout quality wins.</p>
      )}

      <h4 id={worstLossHeadingId} className={styles.label}>
        Worst loss
      </h4>
      {evidence.worst_loss ? (
        <ul className={styles.list} aria-labelledby={worstLossHeadingId}>
          <GameLine game={evidence.worst_loss} />
        </ul>
      ) : (
        <p className={styles.empty}>No losses.</p>
      )}

      <h4 id={fullScheduleHeadingId} className={styles.label}>
        Full schedule
      </h4>
      {orderedGames.length > 0 ? (
        <ul className={styles.list} aria-labelledby={fullScheduleHeadingId}>
          {orderedGames.map((game, index) => (
            <GameLine
              key={`${game.opponent_team_id}-${game.week ?? 'na'}-${index}`}
              game={game}
              highlight={highlightByGame.get(gameKey(game))}
            />
          ))}
        </ul>
      ) : (
        <p className={styles.empty}>No games played.</p>
      )}
    </section>
  )
}
