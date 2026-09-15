import { useId, useState } from 'react'
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
}

const SHARE_TITLE = 'My Team Is Better'

const DEFAULT_LABEL = 'Share this verdict'
const COPIED_STATUS = 'Link copied'
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
 */
export function ShareButton({ url, label = DEFAULT_LABEL }: ShareButtonProps) {
  const fieldId = useId()
  const [status, setStatus] = useState('')
  const [showManualCopy, setShowManualCopy] = useState(false)

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

  return (
    <div className={styles.share}>
      <button
        type="button"
        className={styles.shareButton}
        onClick={() => void handleClick()}
      >
        {label}
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
        </div>
      )}
    </div>
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
