import { Link } from 'react-router-dom'
import type { CreditsDataSourceOut } from '../../lib/api/types'
import styles from './PlayerStatsCredit.module.css'

export interface PlayerStatsCreditProps {
  /**
   * The `nflverse_player_stats` credit from `/api/credits`, picked by id; or
   * `null` while it loads or if it can't be had.
   */
  credit: CreditsDataSourceOut | null
}

/**
 * Credits the player data where it appears (issue #296). The name, link and
 * note all come from the API, like the About page's credits; with no credit
 * in hand it points at the About page's data section instead of saying
 * nothing.
 */
export function PlayerStatsCredit({ credit }: PlayerStatsCreditProps) {
  if (credit === null) {
    return (
      <p className={styles.credit}>
        Where these player stats come from:{' '}
        <Link to="/about#data">How This Works</Link>.
      </p>
    )
  }
  return (
    <p className={styles.credit}>
      Player stats from{' '}
      <a href={credit.url} target="_blank" rel="noreferrer">
        {credit.name}
      </a>
      . <span className={styles.note}>{credit.note}</span>
    </p>
  )
}
