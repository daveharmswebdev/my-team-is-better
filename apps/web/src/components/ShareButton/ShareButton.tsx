import { useId, useState } from 'react'
import styles from './ShareButton.module.css'

export interface ShareButtonProps {
  /** The absolute share link to hand off (issue #184). */
  url: string
}

/** What the last click managed to do with the link. */
type ShareOutcome = 'idle' | 'copied' | 'manual'

const SHARE_TITLE = 'My Team Is Better'

/**
 * Hands a verdict's share link to the user by the best means the browser
 * offers (issue #184), in order:
 *
 * 1. the native share sheet (`navigator.share`), where there is one. Closing
 *    the sheet rejects with an `AbortError`; that is the user changing their
 *    mind, so it is a silent no-op. Any other rejection falls through;
 * 2. the clipboard, confirmed with a polite "Link copied" status;
 * 3. a read-only, labeled field holding the link, when the clipboard is
 *    missing or refuses -- so the link can always be copied by hand.
 *
 * The status region is rendered from the start, empty, because a live region
 * inserted together with its text is announced unreliably.
 */
export function ShareButton({ url }: ShareButtonProps) {
  const fieldId = useId()
  const [outcome, setOutcome] = useState<ShareOutcome>('idle')

  async function handleClick() {
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
      setOutcome('copied')
    } catch {
      setOutcome('manual')
    }
  }

  return (
    <div className={styles.share}>
      <button
        type="button"
        className={styles.shareButton}
        onClick={() => void handleClick()}
      >
        Share this verdict
      </button>
      <p role="status" className={styles.status}>
        {outcome === 'copied' ? 'Link copied' : ''}
      </p>
      {outcome === 'manual' && (
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
