import type { PlayerHeadToHeadOut } from '../../lib/api/types'
import {
  GAMES_LIST_LABEL,
  formatGameWhen,
  headToHeadRecordCopy,
  headToHeadStatLine,
  neverMetCopy,
} from '../../lib/playerCompare'
import styles from './PlayerHeadToHead.module.css'

export interface PlayerHeadToHeadProps {
  aName: string
  bName: string
  /** One season type's head-to-head, `a`'s record against `b`. */
  headToHead: PlayerHeadToHeadOut
}

/**
 * Two players' games against each other as opposing starting quarterbacks,
 * of one season type (issue #301): `a`'s record against `b`, then each game
 * in the API's chronological order with both teams' points and each
 * starter's line: the stat groups he recorded in that game, by the career
 * table's rule (issue #352, `headToHeadStatLine`). Games neither started, or started for the same team, are not
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
      {/* eslint-disable-next-line jsx-a11y/no-redundant-roles -- `list-style: none` drops list semantics in Safari/VoiceOver, so role="list" is stated on purpose */}
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
            <p className={styles.line}>
              {headToHeadStatLine(aName, game.a_stats)}
            </p>
            <p className={styles.line}>
              {headToHeadStatLine(bName, game.b_stats)}
            </p>
          </li>
        ))}
      </ol>
    </div>
  )
}
