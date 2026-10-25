import { Link } from 'react-router-dom'
import type { CreditsDataSourceOut } from '../../lib/api/types'
import styles from './PlayerStatsCredit.module.css'

export interface PlayerStatsCreditProps {
  /**
   * The `nflverse_player_stats` credit from `/api/credits`, picked by id; or
   * `null` while it loads or if it can't be had.
   */
  credit: CreditsDataSourceOut | null
  /**
   * A QB score is on screen (issue #459): credit the EP model its EPA comes
   * from too, beside the stats credit.
   */
  epModel?: boolean
}

/**
 * The QB score's EPA comes from nflfastR's expected-points model. Static
 * copy: `/api/credits` has no entry of its own for the model, and this sits
 * beside -- never instead of -- the API's nflverse credit.
 */
const EP_MODEL_CREDIT =
  "The QB score's expected points come from nflfastR's EP model, by Ben Baldwin & Sebastian Carl."

/**
 * Credits the player data where it appears (issue #296). The name, link and
 * note all come from the API, like the About page's credits; with no credit
 * in hand it points at the About page's data section instead of saying
 * nothing. With a QB score on screen it credits the EP model as well.
 */
export function PlayerStatsCredit({
  credit,
  epModel = false,
}: PlayerStatsCreditProps) {
  const ep = epModel ? (
    <>
      {' '}
      <span className={styles.ep}>{EP_MODEL_CREDIT}</span>
    </>
  ) : null
  if (credit === null) {
    return (
      <p className={styles.credit}>
        Where these player stats come from:{' '}
        <Link to="/about#data">How This Works</Link>.{ep}
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
      {ep}
    </p>
  )
}
