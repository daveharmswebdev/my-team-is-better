import { useId, useState } from 'react'
import { EPA_EXPLANATION } from '../../lib/playerStats'
import styles from './EpaExplanation.module.css'

export interface EpaExplanationProps {
  /** Start with the explanation showing (stories, mostly). */
  defaultOpen?: boolean
}

/** The disclosure button's text, and so the region's name too. */
const LABEL = 'What is EPA?'

/**
 * What EPA is and how each rate on the page was computed (issue #347, under
 * #183's bar: show the math). A disclosure: a real button, so a keyboard
 * reaches it and a screen reader hears it expanded or collapsed, which shows
 * and hides a region the button names. Placed wherever an EPA column is.
 */
export function EpaExplanation({ defaultOpen = false }: EpaExplanationProps) {
  const [open, setOpen] = useState(defaultOpen)
  const buttonId = useId()
  const panelId = useId()
  return (
    <div className={styles.wrap}>
      <button
        type="button"
        id={buttonId}
        className={styles.toggle}
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => {
          setOpen((current) => !current)
        }}
      >
        <span className={styles.chevron} aria-hidden="true">
          {open ? '▾' : '▸'}
        </span>{' '}
        {LABEL}
      </button>
      <div
        id={panelId}
        role="region"
        aria-labelledby={buttonId}
        className={styles.panel}
        hidden={!open}
      >
        <p>{EPA_EXPLANATION}</p>
      </div>
    </div>
  )
}
