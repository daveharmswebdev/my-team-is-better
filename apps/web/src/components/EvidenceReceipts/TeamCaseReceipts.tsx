import { useId } from 'react'
import type {
  GameResult,
  OpponentResultOut,
  TeamCaseOut,
} from '../../lib/api/types'
import { formatRating } from '../../lib/formatRating'
import { formatRecord } from '../../lib/formatRecord'
import { resultLabel } from '../../lib/resultLabel'
import { EloLedgerDisclosure } from './EloLedgerDisclosure'
import { RatingBreakdownDisclosure } from './RatingBreakdownDisclosure'
import { ratingWorkFor } from './ratingBreakdownByMethod'
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
 *
 * Every game list is keyed on `game_id` (`games.id`, issue #218), the one
 * identity a game has: a rematch against the same opponent in one season
 * (a regular-season game and a conference-title rematch, say) is two games
 * with two keys, both in the lists and in the quality-win/worst-loss
 * cross-reference below.
 */
export function TeamCaseReceipts({ evidence }: TeamCaseReceiptsProps) {
  const orderedGames = [...evidence.games].sort(bySeasonOrder)

  const highlightByGame = new Map<number, Highlight>()
  for (const game of evidence.quality_wins) {
    highlightByGame.set(game.game_id, 'Quality win')
  }
  if (evidence.worst_loss) {
    highlightByGame.set(evidence.worst_loss.game_id, 'Worst loss')
  }

  const headingId = useId()
  const qualityWinsHeadingId = `${headingId}-quality-wins`
  const worstLossHeadingId = `${headingId}-worst-loss`
  const fullScheduleHeadingId = `${headingId}-full-schedule`
  // Issues #153/#183: by method, never by the breakdown's emptiness.
  const work = ratingWorkFor(evidence.method, evidence.elo_ledger)

  return (
    <section
      aria-label={`${evidence.team_name} evidence`}
      className={styles.receipts}
    >
      <div className={styles.stats}>
        Record: {formatRecord(evidence.wins, evidence.losses, evidence.ties)}{' '}
        &middot; Rank #{evidence.rank} &middot; Rating{' '}
        {work.kind === 'keener-breakdown' ? (
          <RatingBreakdownDisclosure
            teamName={evidence.team_name}
            method={evidence.method}
            rating={evidence.rating}
            breakdown={evidence.rating_breakdown}
          />
        ) : work.kind === 'elo-ledger' ? (
          <EloLedgerDisclosure
            teamName={evidence.team_name}
            rating={evidence.rating}
            ledger={work.ledger}
          />
        ) : (
          formatRating(evidence.rating, evidence.method)
        )}
        {work.kind === 'no-disclosure' && (
          <p className={styles.ratingNote}>{work.explainer}</p>
        )}
        {work.kind === 'ledger-unavailable' && (
          <p className={styles.ratingNote}>{work.note}</p>
        )}
      </div>

      <h4 id={qualityWinsHeadingId} className={styles.label}>
        Quality wins
      </h4>
      {evidence.quality_wins.length > 0 ? (
        <ul className={styles.list} aria-labelledby={qualityWinsHeadingId}>
          {evidence.quality_wins.map((game) => (
            <GameLine key={game.game_id} game={game} />
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
          {orderedGames.map((game) => (
            <GameLine
              key={game.game_id}
              game={game}
              highlight={highlightByGame.get(game.game_id)}
            />
          ))}
        </ul>
      ) : (
        <p className={styles.empty}>No games played.</p>
      )}
    </section>
  )
}
