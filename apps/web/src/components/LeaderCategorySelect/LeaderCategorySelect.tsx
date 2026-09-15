import { useId } from 'react'
import type { PlayerLeaderCategory } from '../../lib/api/types'
import {
  PLAYER_LEADER_CATEGORIES,
  isPlayerLeaderCategory,
} from '../../lib/api/types'
import { CATEGORY_LABEL } from '../../lib/playerStats'
import styles from './LeaderCategorySelect.module.css'

export interface LeaderCategorySelectProps {
  value: PlayerLeaderCategory
  onChange: (value: PlayerLeaderCategory) => void
}

/**
 * Which leaderboard to show (issue #312): Passing or Rushing. Founder
 * decision (epic #311): this picks a stat *category*, not a position -- the
 * rushing board ranks every player with a carry, and shows each one's
 * position in a column.
 *
 * A native `select` with a real `label`, so it is named, reachable and
 * operable from the keyboard with no ARIA of its own. The options come from
 * `PLAYER_LEADER_CATEGORIES`, so a category added to the mirror of the
 * engine's list becomes selectable here and nowhere else.
 */
export function LeaderCategorySelect({
  value,
  onChange,
}: LeaderCategorySelectProps) {
  const id = useId()
  return (
    <div className={styles.field}>
      <label className={styles.label} htmlFor={id}>
        Stat category
      </label>
      <select
        id={id}
        className={styles.select}
        value={value}
        onChange={(event) => {
          const next = event.target.value
          if (isPlayerLeaderCategory(next) && next !== value) {
            onChange(next)
          }
        }}
      >
        {PLAYER_LEADER_CATEGORIES.map((category) => (
          <option key={category} value={category}>
            {CATEGORY_LABEL[category]}
          </option>
        ))}
      </select>
    </div>
  )
}
