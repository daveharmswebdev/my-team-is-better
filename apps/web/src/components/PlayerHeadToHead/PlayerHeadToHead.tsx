import type { PlayerHeadToHeadOut, PlayerStatsOut } from '../../lib/api/types'
import {
  GAMES_LIST_LABEL,
  formatGameWhen,
  headToHeadRecordCopy,
  neverMetCopy,
} from '../../lib/playerCompare'
import { NOT_RECORDED, formatStat } from '../../lib/playerStats'
import styles from './PlayerHeadToHead.module.css'

export interface PlayerHeadToHeadProps {
  aName: string
  bName: string
  /** One season type's head-to-head, `a`'s record against `b`. */
  headToHead: PlayerHeadToHeadOut
}

/** "328 passing yards", "1 TD", or "TDs not recorded". */
function statPart(
  value: number | null,
  singular: string,
  plural: string,
): string {
  if (value === null) {
    return `${plural} ${NOT_RECORDED}`
  }
  return `${formatStat(value)} ${value === 1 ? singular : plural}`
}

/** A starter's passing line in one game; no stat line at all is "not recorded". */
function passingLine(name: string, stats: PlayerStatsOut | null): string {
  if (stats === null) {
    return `${name}: ${NOT_RECORDED}`
  }
  return `${name}: ${[
    statPart(stats.passing_yards, 'passing yard', 'passing yards'),
    statPart(stats.passing_tds, 'TD', 'TDs'),
    statPart(stats.passing_interceptions, 'INT', 'INTs'),
  ].join(', ')}`
}

/**
 * Two players' games against each other as opposing starting quarterbacks,
 * of one season type (issue #301): `a`'s record against `b`, then each game
 * in the API's chronological order with both teams' points and each QB's
 * passing line. Games neither started, or started for the same team, are not
 * in the API's list, and nothing here adds them.
 */
export function PlayerHeadToHead({
  aName,
  bName,
  headToHead,
}: PlayerHeadToHeadProps) {
  if (headToHead.games.length === 0) {
    return (
      <p className={styles.none}>
        {neverMetCopy(aName, bName, headToHead.season_type)}
      </p>
    )
  }
  return (
    <div className={styles.wrap}>
      <p className={styles.record}>
        {headToHeadRecordCopy(aName, bName, headToHead.record)}
      </p>
      <ol
        className={styles.games}
        // Named explicitly, and `role` kept, since `list-style: none` drops
        // list semantics in some browsers.
        role="list"
        aria-label={GAMES_LIST_LABEL[headToHead.season_type]}
      >
        {headToHead.games.map((game, index) => (
          <li
            key={game.source_id ?? `${game.season}-${index}`}
            className={styles.game}
          >
            <p className={styles.when}>{formatGameWhen(game)}</p>
            <p className={styles.score}>
              {`${game.a_team} ${game.a_points}, ${game.b_team} ${game.b_points}`}
            </p>
            <p className={styles.line}>{passingLine(aName, game.a_stats)}</p>
            <p className={styles.line}>{passingLine(bName, game.b_stats)}</p>
          </li>
        ))}
      </ol>
    </div>
  )
}
