import { useEffect, useId, useRef, useState } from 'react'
import type { RefObject } from 'react'
import styles from './ShareButton.module.css'

export interface ShareButtonProps {
  /** The absolute share link to hand off (issue #184). */
  url: string
  /**
   * The button's visible text, which is also its accessible name. Defaults to
   * the verdict wording every team-flow caller uses; the NFL player
   * comparison passes its own (issue #310).
   */
  label?: string
  /**
   * Where the button sits (issue #474). `inline` (the default) is a primary
   * button in the content's flow, which a desktop view puts at the top of
   * its panel. `floating` is a phone's floating action button, fixed
   * bottom-right over the scrolling view and always on screen; render it
   * last in the content, where its in-flow slot keeps the last line clear.
   */
  layout?: ShareButtonLayout
}

export type ShareButtonLayout = 'inline' | 'floating'

const SHARE_TITLE = 'My Team Is Better'

const DEFAULT_LABEL = 'Share this verdict'
const COPIED_STATUS = 'Link copied'
/** How long "Link copied" stays up: long enough to read and be announced. */
const COPIED_STATUS_MS = 4000
const MANUAL_COPY_STATUS =
  "Couldn't copy automatically -- the link is in the field below."

/**
 * Hands a verdict's share link to the user by the best means the browser
 * offers (issue #184), in order:
 *
 * 1. the native share sheet (`navigator.share`), where there is one. Closing
 *    the sheet rejects with an `AbortError`; that is the user changing their
 *    mind, so it is a silent no-op. Any other rejection falls through;
 * 2. the clipboard, confirmed with a polite "Link copied" status;
 * 3. a read-only, labeled field holding the link, when the clipboard is
 *    missing or refuses -- announced through the same status, so the
 *    fallback is never silent -- so the link can always be copied by hand.
 *
 * The status region is rendered from the start, empty, because a live region
 * inserted together with its text is announced unreliably. It is emptied at
 * the start of every attempt, so a repeat of the same message is a change a
 * screen reader announces again.
 *
 * Nothing it shows stays forever (issue #474): "Link copied" clears itself
 * after a few seconds, and the manual-copy box has a "Dismiss the link"
 * button that closes it and returns focus to Share.
 */
export function ShareButton({
  url,
  label = DEFAULT_LABEL,
  layout = 'inline',
}: ShareButtonProps) {
  const fieldId = useId()
  const [status, setStatus] = useState('')
  const [showManualCopy, setShowManualCopy] = useState(false)
  const buttonRef = useRef<HTMLButtonElement>(null)
  const stackRef = useRef<HTMLDivElement>(null)
  const floating = layout === 'floating'
  const stackHeight = useObservedHeight(stackRef, floating)

  // "Link copied" is a toast, not a fixture (#474): it goes after long
  // enough to read and be announced. The cleanup drops the timer on
  // unmount and whenever the status changes first.
  useEffect(() => {
    if (status !== COPIED_STATUS) {
      return
    }
    const timer = setTimeout(() => setStatus(''), COPIED_STATUS_MS)
    return () => clearTimeout(timer)
  }, [status])

  /** Closes the manual-copy box and puts focus back where it came from. */
  function dismissManualCopy() {
    setShowManualCopy(false)
    setStatus('')
    buttonRef.current?.focus()
  }

  async function handleClick() {
    setStatus('')
    // `lib.dom` types `share` as always present; at run time it often isn't.
    if (typeof navigator.share === 'function') {
      try {
        await navigator.share({ title: SHARE_TITLE, url })
        return
      } catch (error) {
        if (isAbortError(error)) {
          return
        }
      }
    }
    try {
      // Throws a TypeError, caught below, when `navigator.clipboard` is
      // missing (e.g. an insecure origin).
      await navigator.clipboard.writeText(url)
      setStatus(COPIED_STATUS)
    } catch {
      setShowManualCopy(true)
      setStatus(MANUAL_COPY_STATUS)
    }
  }

  const controls = (
    <>
      <button
        ref={buttonRef}
        type="button"
        className={floating ? styles.fab : styles.shareButton}
        // The FAB's visible text is just "Share"; the full label stays its
        // accessible name, which starts with that word (WCAG 2.5.3).
        aria-label={floating ? label : undefined}
        onClick={() => void handleClick()}
      >
        {floating ? (
          <>
            <ShareIcon />
            Share
          </>
        ) : (
          label
        )}
      </button>
      <p
        role="status"
        className={
          status === MANUAL_COPY_STATUS
            ? `${styles.status} ${styles.statusManual}`
            : styles.status
        }
      >
        {status}
      </p>
      {showManualCopy && (
        <div className={styles.manual}>
          <label htmlFor={fieldId} className={styles.manualLabel}>
            Copy this link
          </label>
          <input
            id={fieldId}
            className={styles.manualField}
            type="text"
            readOnly
            value={url}
            onFocus={(event) => event.currentTarget.select()}
          />
          <button
            type="button"
            className={styles.dismiss}
            onClick={dismissManualCopy}
          >
            Dismiss the link
          </button>
        </div>
      )}
    </>
  )

  if (!floating) {
    return (
      <div className={styles.share} data-layout="inline">
        {controls}
      </div>
    )
  }
  // The slot stays in the content's flow, as tall as the whole floating
  // stack -- the button plus the toast or manual-copy box it is showing --
  // and its margins, so at the bottom of the scroll the last line sits above
  // the stack instead of under it. The stack itself is fixed to the
  // viewport. Until it is measured (or without ResizeObserver), the CSS
  // height covers the button alone.
  return (
    <div
      className={styles.slot}
      data-layout="floating"
      style={
        stackHeight === null
          ? undefined
          : {
              height: `calc(${stackHeight}px + var(--fab-gap) + var(--sp-2))`,
            }
      }
    >
      <div ref={stackRef} className={styles.floating}>
        {controls}
      </div>
    </div>
  )
}

/**
 * The element's laid-out height, kept current with a `ResizeObserver` while
 * `enabled`; `null` before the first measurement or where there is none.
 */
function useObservedHeight(
  ref: RefObject<HTMLElement | null>,
  enabled: boolean,
): number | null {
  const [height, setHeight] = useState<number | null>(null)
  useEffect(() => {
    const element = ref.current
    if (!enabled || element === null || typeof ResizeObserver !== 'function') {
      return
    }
    const observer = new ResizeObserver(() => setHeight(element.offsetHeight))
    observer.observe(element)
    return () => observer.disconnect()
  }, [ref, enabled])
  return height
}

/** The three-node "share" glyph; decorative, the button's name says it. */
function ShareIcon() {
  return (
    <svg
      aria-hidden="true"
      focusable="false"
      className={styles.icon}
      viewBox="0 0 24 24"
      width="20"
      height="20"
    >
      <circle cx="18" cy="5" r="3" />
      <circle cx="6" cy="12" r="3" />
      <circle cx="18" cy="19" r="3" />
      <path d="M8.6 13.5l6.8 4M15.4 6.5l-6.8 4" />
    </svg>
  )
}

function isAbortError(error: unknown): boolean {
  return (
    typeof error === 'object' &&
    error !== null &&
    'name' in error &&
    error.name === 'AbortError'
  )
}
