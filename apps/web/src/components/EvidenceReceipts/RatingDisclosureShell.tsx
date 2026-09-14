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
   *   view. The desktop popover is also wider. A region can also set
   *   `data-min-visible-items` to the number of its items that must show
   *   whole at once.
   */
  scroll?: 'panel' | 'region'
  /** The panel body, rendered below the heading. */
  children: ReactNode
}

/** Gap, in px, kept between the popover and the viewport edge. */
const VIEWPORT_MARGIN = 8
/**
 * Narrowest the popover may get when it opens beside the trigger; with less
 * room than this on both sides it opens above or below instead.
 */
const MIN_SIDE_WIDTH = 280
/** Largest share of the viewport's height a popover takes by default. */
const DEFAULT_HEIGHT_SHARE = 0.8

/**
 * Attribute a scroll region sets to the number of its items that must be
 * fully visible at once (`data-min-visible-items={4}`). The popover grows
 * past its default height (up to the room it has) until they are.
 */
const MIN_VISIBLE_ITEMS_ATTRIBUTE = 'data-min-visible-items'

type Side = 'right' | 'left' | 'below' | 'above'

/**
 * Places the desktop popover so all of it is on screen, wherever the trigger
 * sits, and keeps it touching the trigger so the pointer can travel into it.
 *
 * - Beside the trigger (right, else left: whichever has room, else more
 *   room), where the whole viewport height is available. The popover slides
 *   up or down to stay on screen, always overlapping the trigger's row.
 * - Only when neither side is at least `MIN_SIDE_WIDTH` wide (a very narrow
 *   window) does it open above or below, on whichever has more room.
 *
 * Height: `DEFAULT_HEIGHT_SHARE` of the viewport, then grown until the scroll
 * region's `MIN_VISIBLE_ITEMS_ATTRIBUTE` items are fully visible, never past
 * the room available. The gap between trigger and panel is the popover's own
 * padding (see `data-side` in the stylesheet), so it counts as hovering.
 */
function placePopover(popover: HTMLElement, anchor: HTMLElement): Side {
  const style = popover.style
  style.top = ''
  style.bottom = ''
  style.left = ''
  style.right = ''
  style.width = ''
  style.maxHeight = ''
  style.translate = ''

  const viewportWidth = document.documentElement.clientWidth
  const viewportHeight = window.innerHeight
  const trigger = anchor.getBoundingClientRect()
  const naturalWidth = popover.getBoundingClientRect().width
  const roomRight = viewportWidth - VIEWPORT_MARGIN - trigger.right
  const roomLeft = trigger.left - VIEWPORT_MARGIN
  const fullHeight = viewportHeight - 2 * VIEWPORT_MARGIN

  let side: Side
  let heightLimit: number
  if (Math.max(roomRight, roomLeft) >= Math.min(naturalWidth, MIN_SIDE_WIDTH)) {
    side = roomRight >= naturalWidth || roomRight >= roomLeft ? 'right' : 'left'
    popover.dataset.side = side
    const room = side === 'right' ? roomRight : roomLeft
    style.width = `${Math.min(naturalWidth, room)}px`
    style.left = side === 'right' ? '100%' : 'auto'
    style.right = side === 'left' ? '100%' : 'auto'
    style.top = '0px'
    style.bottom = 'auto'
    heightLimit = fullHeight
  } else {
    const roomBelow = viewportHeight - VIEWPORT_MARGIN - trigger.bottom
    const roomAbove = trigger.top - VIEWPORT_MARGIN
    side = roomBelow >= roomAbove ? 'below' : 'above'
    popover.dataset.side = side
    style.top = side === 'below' ? '100%' : 'auto'
    style.bottom = side === 'above' ? '100%' : 'auto'
    heightLimit = Math.max(roomBelow, roomAbove)
    const rect = popover.getBoundingClientRect()
    let shift = 0
    if (rect.right > viewportWidth - VIEWPORT_MARGIN) {
      shift = viewportWidth - VIEWPORT_MARGIN - rect.right
    }
    if (rect.left + shift < VIEWPORT_MARGIN) {
      shift = VIEWPORT_MARGIN - rect.left
    }
    if (shift !== 0) {
      style.translate = `${shift}px 0`
    }
  }

  const defaultHeight = Math.min(
    DEFAULT_HEIGHT_SHARE * viewportHeight,
    heightLimit,
  )
  style.maxHeight = `${defaultHeight}px`
  growUntilItemsVisible(popover, heightLimit)

  if (side === 'right' || side === 'left') {
    // Line the panel's heading up with the trigger, then slide it back on
    // screen. The popover is at least as tall as the trigger, so a clamped
    // position still overlaps the trigger's row.
    const height = popover.getBoundingClientRect().height
    const wanted = trigger.top - VIEWPORT_MARGIN
    const top = Math.min(
      Math.max(wanted, VIEWPORT_MARGIN),
      viewportHeight - VIEWPORT_MARGIN - height,
    )
    style.top = `${Math.max(top, VIEWPORT_MARGIN) - trigger.top}px`
  }
  return side
}

/**
 * Raises the popover's max-height, up to `heightLimit`, until the first N
 * items of its scroll region (N from `MIN_VISIBLE_ITEMS_ATTRIBUTE`) are fully
 * inside the region's visible box.
 */
function growUntilItemsVisible(popover: HTMLElement, heightLimit: number) {
  const region = popover.querySelector<HTMLElement>(
    `[${MIN_VISIBLE_ITEMS_ATTRIBUTE}]`,
  )
  if (region === null) {
    return
  }
  const wanted = Number(region.getAttribute(MIN_VISIBLE_ITEMS_ATTRIBUTE))
  const items = region.children
  const count = Math.min(Number.isFinite(wanted) ? wanted : 0, items.length)
  const last = items.item(count - 1)
  if (count < 1 || last === null) {
    return
  }
  const regionTop =
    region.getBoundingClientRect().top + region.clientTop - region.scrollTop
  const needed = last.getBoundingClientRect().bottom - regionTop
  const deficit = Math.ceil(needed - region.clientHeight)
  if (deficit > 0) {
    const height = popover.getBoundingClientRect().height
    popover.style.maxHeight = `${Math.min(height + deficit, heightLimit)}px`
  }
}

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
  const wrapperRef = useRef<HTMLSpanElement>(null)
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

  // Every desktop popover is placed on screen next to its trigger, wherever
  // the trigger sits on the page (see `placePopover`). Layout only, before
  // paint.
  useLayoutEffect(() => {
    const popover = popoverRef.current
    const anchor = wrapperRef.current
    if (!open || isTouch || popover === null || anchor === null) {
      return
    }
    placePopover(popover, anchor)
  }, [open, isTouch])

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
      ref={wrapperRef}
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
