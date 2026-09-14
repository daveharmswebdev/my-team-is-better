import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react'
import type { FocusEvent, KeyboardEvent, MouseEvent, ReactNode } from 'react'
import styles from './RatingDisclosureShell.module.css'

export interface RatingDisclosureShellProps {
  /** The rating exactly as the card prints it; the trigger's visible text and accessible name. */
  triggerLabel: string
  /** The panel's heading and the dialog's accessible name. */
  title: string
  /** Accessible name of the touch modal's close button. */
  closeLabel: string
  /**
   * What scrolls when the content outgrows the viewport:
   * - `'panel'` (default): the whole panel scrolls.
   * - `'region'`: the panel is a fixed frame, and only the child that marks
   *   itself as the scroll region (with `flex: 1 1 auto; min-height: 0;
   *   overflow-y: auto`) scrolls, so everything above and below it stays in
   *   view. The desktop popover is also wider, and is kept inside the
   *   viewport.
   */
  scroll?: 'panel' | 'region'
  /** The panel body, rendered below the heading. */
  children: ReactNode
}

/** Smallest height, in px, the viewport-fitted popover will shrink to. */
const MIN_FITTED_POPOVER_HEIGHT = 240
/** Gap, in px, kept between the fitted popover and the viewport edge. */
const VIEWPORT_MARGIN = 8

/**
 * Reports whether the current pointer is touch/coarse (mobile: tap-to-open
 * modal) rather than hover-capable/fine (desktop: hover-to-open popover).
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

function classes(...names: Array<string | false | undefined>): string {
  return names.filter(Boolean).join(' ')
}

/**
 * The show-your-work disclosure every rating uses (issues #31, #183): a
 * trigger showing the rating, a hover popover on desktop and a tap modal on
 * touch, with the same close rules for all of them -- pointer leaving, focus
 * leaving, Escape, the close button and the backdrop. It knows nothing
 * about any rating method; each method's panel content is its `children`.
 */
export function RatingDisclosureShell({
  triggerLabel,
  title,
  closeLabel,
  scroll = 'panel',
  children,
}: RatingDisclosureShellProps) {
  const isTouch = useIsTouchInteraction()
  const [open, setOpen] = useState(false)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const closeButtonRef = useRef<HTMLButtonElement>(null)
  const popoverRef = useRef<HTMLDivElement>(null)
  const panelId = useId()
  const framed = scroll === 'region'

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
  // contract. Focus leaving the disclosure while it's open (e.g. tabbing
  // to the next field) closes it, so a popover never gets stranded; focus
  // moving from the trigger *into* the popover (a link, a scrollable list)
  // keeps it open.
  function handleBlur(event: FocusEvent<HTMLSpanElement>) {
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
    // Uses only the stable state setter and a ref, so it needs no other
    // dependency than `open`.
    function handleDocumentKeyDown(event: globalThis.KeyboardEvent) {
      if (event.key === 'Escape') {
        setOpen(false)
        triggerRef.current?.focus()
      }
    }
    document.addEventListener('keydown', handleDocumentKeyDown)
    return () => document.removeEventListener('keydown', handleDocumentKeyDown)
  }, [open])

  useEffect(() => {
    if (open && isTouch) {
      closeButtonRef.current?.focus()
    }
  }, [open, isTouch])

  // A framed popover is wide and holds a scroll region, so it must fit on
  // screen: shift it sideways back inside the viewport, and cap its height at
  // 80vh or the room below the trigger, whichever is smaller (never below a
  // usable minimum), so the region (not the page) takes the overflow. Layout
  // only, before paint.
  useLayoutEffect(() => {
    const popover = popoverRef.current
    if (!open || isTouch || !framed || popover === null) {
      return
    }
    popover.style.translate = ''
    popover.style.maxHeight = ''
    const rect = popover.getBoundingClientRect()
    const viewportWidth = document.documentElement.clientWidth
    let shift = 0
    if (rect.right > viewportWidth - VIEWPORT_MARGIN) {
      shift = viewportWidth - VIEWPORT_MARGIN - rect.right
    }
    if (rect.left + shift < VIEWPORT_MARGIN) {
      shift = VIEWPORT_MARGIN - rect.left
    }
    if (shift !== 0) {
      popover.style.translate = `${shift}px 0`
    }
    const roomBelow = window.innerHeight - rect.top - VIEWPORT_MARGIN
    popover.style.maxHeight = `min(80vh, ${Math.max(roomBelow, MIN_FITTED_POPOVER_HEIGHT)}px)`
  }, [open, isTouch, framed])

  const panel = (
    <div className={classes(styles.panel, framed && styles.framed)}>
      <div className={styles.panelHeader}>
        <h5 className={styles.panelTitle}>{title}</h5>
        {isTouch && (
          <button
            ref={closeButtonRef}
            type="button"
            className={styles.closeButton}
            onClick={closeAndRefocus}
            aria-label={closeLabel}
          >
            &times;
          </button>
        )}
      </div>
      {children}
    </div>
  )

  return (
    <span
      className={styles.wrapper}
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
      onBlur={handleBlur}
    >
      <button
        ref={triggerRef}
        type="button"
        className={styles.trigger}
        onClick={handleTriggerClick}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-controls={open ? panelId : undefined}
      >
        {triggerLabel}
      </button>

      {open && !isTouch && (
        <div
          ref={popoverRef}
          id={panelId}
          role="dialog"
          aria-label={title}
          className={classes(styles.popover, framed && styles.framed)}
        >
          {panel}
        </div>
      )}

      {open && isTouch && (
        <div
          className={classes(styles.overlay, framed && styles.framed)}
          onClick={handleOverlayClick}
          onKeyDown={handleOverlayKeyDown}
        >
          <div
            id={panelId}
            role="dialog"
            aria-modal="true"
            aria-label={title}
            className={classes(styles.modal, framed && styles.framed)}
          >
            {panel}
          </div>
        </div>
      )}
    </span>
  )
}
