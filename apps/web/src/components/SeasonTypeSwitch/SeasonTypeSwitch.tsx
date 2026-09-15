import { useId } from 'react'
import type { PlayerSeasonType } from '../../lib/api/types'
import { PLAYER_SEASON_TYPES } from '../../lib/api/types'
import { SEASON_TYPE_LABEL } from '../../lib/playerStats'
import styles from './SeasonTypeSwitch.module.css'

export interface SeasonTypeSwitchProps {
  value: PlayerSeasonType
  onChange: (value: PlayerSeasonType) => void
}

/**
 * Regular season / Playoffs (issue #296), drawn as a segmented control.
 * Underneath it is a native radio group in a fieldset, so the arrow keys move
 * between the two, and the checked state and group name reach assistive tech
 * without any ARIA of its own.
 */
export function SeasonTypeSwitch({ value, onChange }: SeasonTypeSwitchProps) {
  const name = useId()
  return (
    <fieldset className={styles.switch}>
      <legend className={styles.legend}>Season type</legend>
      <div className={styles.segments}>
        {PLAYER_SEASON_TYPES.map((seasonType) => (
          <label className={styles.segment} key={seasonType}>
            <input
              className={styles.input}
              type="radio"
              name={name}
              value={seasonType}
              checked={value === seasonType}
              onChange={() => {
                if (seasonType !== value) {
                  onChange(seasonType)
                }
              }}
            />
            <span>{SEASON_TYPE_LABEL[seasonType]}</span>
          </label>
        ))}
      </div>
    </fieldset>
  )
}
