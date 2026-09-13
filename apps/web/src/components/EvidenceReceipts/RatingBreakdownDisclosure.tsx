import { useEffect, useId, useRef, useState } from 'react'
import type { KeyboardEvent, MouseEvent } from 'react'
import { formatRating } from '../../lib/formatRating'
import { formatRecord } from '../../lib/formatRecord'
import type {
  Method,
  OpponentCreditOut,
  RatingBreakdownOut,
} from '../../lib/api/types'
import styles from './RatingBreakdownDisclosure.module.css'

export interface RatingBreakdownDisclosureProps {
  /** Team this breakdown belongs to (used in labels only, not rendered as a heading of its own). */
  teamName: string
  /** The rating method behind `rating`/`breakdown` -- picks every number's display scale via `formatRating`. */
  method: Method
  /** The same rating value `ComparisonReceipts` already displays -- shown again in the footer total so a fan can see it's consistent with the entries + residual below it. */
  rating: number
  breakdown: RatingBreakdownOut
}

/**
 * Reports whether the current pointer is touch/coarse (mobile: tap-to-open
 * modal) rather than hover-capable/fine (desktop: hover-to-open popover).
 * No such pointer-detection helper exists anywhere in this codebase yet, so
 * this is new plumbing local to this component rather than a shared hook --
 * promote it if a second component needs the same distinction.
 */
function useIsTouchInteraction(): boolean {
  const query = '(hover: none), (pointer: coarse)'
  const [isTouch, setIsTouch] = useState(() =>
    typeof window !== 'undefined' && typeof window.matchMedia === 'function'
      ? window.matchMedia(query).matches
      : false,
  )

  useEffect(() => {
    if (
      typeof window === 'undefined' ||
      typeof window.matchMedia !== 'function'
    ) {
      return
    }
    const mediaQueryList = window.matchMedia(query)
    const handleChange = () => setIsTouch(mediaQueryList.matches)
    mediaQueryList.addEventListener('change', handleChange)
    return () => mediaQueryList.removeEventListener('change', handleChange)
  }, [])

  return isTouch
}

/**
 * Per-opponent record for a breakdown row. The engine's per-opponent credit
 * carries `games_played`/`wins`/`losses` but no `ties` field (issue #83), so
 * ties are *derived* here as the games that were neither a win nor a loss --
 * the same arithmetic the engine's own explanation text uses (e.g. "Played
 * them 2 times (1-0-1)"). Clamped at 0 so a malformed entry can never render
 * a negative tie count.
 */
function opponentRecord(entry: OpponentCreditOut): string {
  const derivedTies = Math.max(
    0,
    entry.games_played - entry.wins - entry.losses,
  )
  return formatRecord(entry.wins, entry.losses, derivedTies)
}

/**
 * Hover popover (desktop) / tap modal (mobile) anchored to a team's rating
 * value, showing the per-opponent Keener credit breakdown behind it
 * (issue #31). `residual_contribution` is real math (a fixed connectivity
 * regularizer plus the credit matrix's dominant eigenvalue being below 1),
 * typically ~47-53% of a team's rating -- it is labeled as its own named
 * thing ("Rating-system baseline"), never folded into "other"/rounding.
 */
export function RatingBreakdownDisclosure({
  teamName,
  method,
  rating,
  breakdown,
}: RatingBreakdownDisclosureProps) {
  const isTouch = useIsTouchInteraction()
  const [open, setOpen] = useState(false)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const closeButtonRef = useRef<HTMLButtonElement>(null)
  const panelId = useId()

  function close() {
    setOpen(false)
  }

  function closeAndRefocus() {
    close()
    triggerRef.current?.focus()
  }

  // Desktop: hover shows/hides the popover. On a touch device there is no
  // hover, so these are no-ops there (tap uses handleTriggerClick instead).
  function handleMouseEnter() {
    if (!isTouch) {
      setOpen(true)
    }
  }
  function handleMouseLeave() {
    if (!isTouch) {
      close()
    }
  }
  // Tab alone only reaches the trigger, it does not open the popover --
  // that keeps a plain Tab-through from popping panels open unexpectedly,
  // while Enter/Space (handleTriggerClick, since both activate a focused
  // <button>) explicitly opens it, matching the "Tab + Enter/Space" keyboard
  // contract. Blurring away from the trigger while it's open (e.g. tabbing
  // to the next field) still closes it, so a popover never gets stranded.
  function handleBlur(event: React.FocusEvent<HTMLSpanElement>) {
    if (!isTouch && !event.currentTarget.contains(event.relatedTarget)) {
      close()
    }
  }

  // Always *opens* (never toggles closed) -- this is what opens the mobile
  // modal on tap, and lets a keyboard user open the desktop popover via
  // Enter/Space. A toggle would be wrong on desktop: a real mouse click
  // necessarily fires `mouseenter` first (already opening it via hover), so
  // a toggling click handler would immediately close what hover just
  // opened. Closing is handled separately (mouseleave/blur/close
  // button/Escape/outside-click), so an always-open click can't get stuck.
  function handleTriggerClick() {
    setOpen(true)
  }

  function handleOverlayClick(event: MouseEvent<HTMLDivElement>) {
    if (event.target === event.currentTarget) {
      closeAndRefocus()
    }
  }

  function handleOverlayKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === 'Escape') {
      closeAndRefocus()
    }
  }

  useEffect(() => {
    if (!open) {
      return
    }
    function handleDocumentKeyDown(event: globalThis.KeyboardEvent) {
      if (event.key === 'Escape') {
        closeAndRefocus()
      }
    }
    document.addEventListener('keydown', handleDocumentKeyDown)
    return () => document.removeEventListener('keydown', handleDocumentKeyDown)
    // eslint-disable-next-line react-hooks/exhaustive-deps -- closeAndRefocus reads refs/state via closures re-created each render; re-subscribing on every render is unnecessary churn for a document-level listener that only needs `open`.
  }, [open])

  useEffect(() => {
    if (open && isTouch) {
      closeButtonRef.current?.focus()
    }
  }, [open, isTouch])

  const entriesTotal = breakdown.entries.reduce(
    (sum, entry) => sum + entry.contribution,
    0,
  )
  const total = entriesTotal + breakdown.residual_contribution

  const panel = (
    <div className={styles.panel}>
      <div className={styles.panelHeader}>
        <h5 className={styles.panelTitle}>{teamName} rating breakdown</h5>
        {isTouch && (
          <button
            ref={closeButtonRef}
            type="button"
            className={styles.closeButton}
            onClick={closeAndRefocus}
            aria-label="Close rating breakdown"
          >
            &times;
          </button>
        )}
      </div>

      <h6 className={styles.sectionLabel}>Credit by opponent</h6>
      {breakdown.entries.length > 0 ? (
        <ul className={styles.rows}>
          {breakdown.entries.map((entry) => (
            <li key={entry.opponent_team_id} className={styles.row}>
              <span className={styles.rowOpponent}>{entry.opponent_name}</span>
              <span className={styles.rowRecord}>{opponentRecord(entry)}</span>
              <span className={styles.rowNum}>
                {formatRating(entry.credit, method)}
              </span>
              <span className={styles.rowNum}>
                {formatRating(entry.contribution, method)}
              </span>
              <span className={styles.rowExplanation}>{entry.explanation}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p className={styles.empty}>No individual opponent credit.</p>
      )}

      <div className={styles.residualRow}>
        <span className={styles.residualLabel}>Rating-system baseline</span>
        <span className={styles.rowNum}>
          {formatRating(breakdown.residual_contribution, method)}
        </span>
      </div>
      <p className={styles.residualNote}>
        Keener&rsquo;s method gives every team a baseline connectivity credit,
        on top of specific opponents &mdash; this is real math, not a rounding
        error, and it&rsquo;s often close to half a team&rsquo;s rating.
      </p>

      <div className={styles.totalRow}>
        <span>Total</span>
        <span className={styles.rowNum}>{formatRating(total, method)}</span>
      </div>
      <p className={styles.totalNote}>
        Matches the displayed rating: {formatRating(rating, method)}
      </p>
    </div>
  )

  return (
    <span
      className={styles.wrapper}
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
    >
      <button
        ref={triggerRef}
        type="button"
        className={styles.trigger}
        onBlur={handleBlur}
        onClick={handleTriggerClick}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-controls={open ? panelId : undefined}
      >
        {formatRating(rating, method)}
      </button>

      {open && !isTouch && (
        <div
          id={panelId}
          role="dialog"
          aria-label={`${teamName} rating breakdown`}
          className={styles.popover}
        >
          {panel}
        </div>
      )}

      {open && isTouch && (
        <div
          className={styles.overlay}
          onClick={handleOverlayClick}
          onKeyDown={handleOverlayKeyDown}
        >
          <div
            id={panelId}
            role="dialog"
            aria-modal="true"
            aria-label={`${teamName} rating breakdown`}
            className={styles.modal}
          >
            {panel}
          </div>
        </div>
      )}
    </span>
  )
}
