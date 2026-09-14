import { useEffect, useId, useRef } from 'react'
import type { MouseEvent, ReactNode, SyntheticEvent } from 'react'
import styles from './VerdictModal.module.css'

export interface VerdictModalProps {
  /** Whether the modal is showing. The parent owns this; the modal never closes itself. */
  open: boolean
  /** The modal's visible heading, and its accessible name. */
  title: string
  /**
   * The close button's accessible name. Its visible text is always "Close",
   * so the name should contain that word (WCAG 2.5.3, label in name).
   */
  closeLabel?: string
  /**
   * Called for every request to close: the close button, Escape, a click on
   * the backdrop, or the browser's own close request (a back gesture).
   */
  onClose: () => void
  /** The modal's content, rendered only while it is open. */
  children: ReactNode
}

/**
 * A dialog opened inside this one, such as a rating's show-your-work panel
 * (`RatingDisclosureShell`), which renders `role="dialog"` only while open.
 */
const NESTED_DIALOG_SELECTOR = '[role="dialog"]'

/**
 * The full-screen verdict modal (issue #198). A shared link's verdict used to
 * render below the whole form, off-screen on a phone. It now opens over the
 * form, in a native `<dialog>` opened with `showModal()`: the browser puts it
 * in the top layer, makes the rest of the page inert (nothing behind it can
 * be focused, clicked or read by assistive technology), and keeps focus
 * inside it.
 *
 * It is controlled: `open` decides, and every close request goes to
 * `onClose`. So Escape and the browser's `cancel` event are both prevented
 * from closing the dialog directly.
 *
 * - **Layout.** The `<dialog>` covers the viewport and is the scroll
 *   container. The page behind it can't scroll. On a phone the panel fills the
 *   screen. On a wider screen it is a centered column with a max width. The
 *   header with the close button is sticky, so it stays in view while the
 *   content scrolls. Because the scroll container is viewport-sized, a
 *   rating's popover, which places itself against the viewport, is not
 *   clipped by a smaller box.
 * - **Escape** closes the modal, except when a dialog is open inside it
 *   (#216). That Escape belongs to the inner dialog, which closes itself.
 *   Which case applies is recorded in the capture phase, before the inner
 *   dialog's own handler removes it.
 * - **Focus** moves to the close button on open. It goes back there whenever
 *   the element holding it disappears, for example a correction pill
 *   replaced by the loading state. Returning focus after close is the
 *   parent's job, since only the parent knows where it should go.
 */
export function VerdictModal({
  open,
  title,
  closeLabel = 'Close',
  onClose,
  children,
}: VerdictModalProps) {
  const dialogRef = useRef<HTMLDialogElement>(null)
  const closeButtonRef = useRef<HTMLButtonElement>(null)
  const titleId = useId()
  /** The latest props, for native listeners that outlive a render. */
  const openRef = useRef(open)
  const onCloseRef = useRef(onClose)
  /** Whether the Escape being dispatched belongs to a dialog inside this one. */
  const escapeIsForNestedDialogRef = useRef(false)

  // Declared first, so the effects below read this render's props.
  useEffect(() => {
    openRef.current = open
    onCloseRef.current = onClose
  })

  useEffect(() => {
    const dialog = dialogRef.current
    if (dialog === null) {
      return
    }
    if (open && !dialog.open) {
      dialog.showModal()
    } else if (!open && dialog.open) {
      dialog.close()
    }
  }, [open])

  // Runs after every render. While open, focus belongs inside. If it isn't
  // there (just opened, or its element was replaced), put it on the close
  // button.
  useEffect(() => {
    const dialog = dialogRef.current
    if (open && dialog !== null && !dialog.contains(document.activeElement)) {
      closeButtonRef.current?.focus()
    }
  })

  useEffect(() => {
    if (!open) {
      return
    }
    function recordEscapeTarget(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        escapeIsForNestedDialogRef.current =
          dialogRef.current?.querySelector(NESTED_DIALOG_SELECTOR) != null
      }
    }
    function handleEscape(event: KeyboardEvent) {
      if (event.key !== 'Escape') {
        return
      }
      // A canceled keydown is not a close request, so the browser won't also
      // fire `cancel`. That makes one Escape exactly one `onClose`.
      event.preventDefault()
      if (!escapeIsForNestedDialogRef.current) {
        onCloseRef.current()
      }
    }
    window.addEventListener('keydown', recordEscapeTarget, true)
    window.addEventListener('keydown', handleEscape)
    return () => {
      window.removeEventListener('keydown', recordEscapeTarget, true)
      window.removeEventListener('keydown', handleEscape)
    }
  }, [open])

  /** A close request that isn't a key press, such as Android's back gesture. */
  function handleCancel(event: SyntheticEvent<HTMLDialogElement>) {
    event.preventDefault()
    onClose()
  }

  /**
   * The dialog closed without the parent asking, which a browser can do
   * without a `cancel` event. The parent hears about it, so its state and the
   * page agree again.
   */
  function handleNativeClose() {
    if (openRef.current) {
      onCloseRef.current()
    }
  }

  /** A click on the dimmed area around the panel, which is the dialog itself. */
  function handleClick(event: MouseEvent<HTMLDialogElement>) {
    if (event.target === event.currentTarget) {
      onClose()
    }
  }

  return (
    // The backdrop click is only a pointer shortcut for Escape and the
    // close button, which are the keyboard ways to do the same thing.
    <dialog
      ref={dialogRef}
      className={styles.dialog}
      aria-labelledby={titleId}
      onCancel={handleCancel}
      onClose={handleNativeClose}
      onClick={handleClick}
    >
      {open && (
        <div className={styles.panel}>
          <div className={styles.header}>
            {/* Not a heading: it names the dialog (`aria-labelledby`), and
                a heading here would sit between the page's h1 and the
                verdict's h4s and skip a level (axe heading-order, #219). */}
            <p id={titleId} className={styles.title}>
              {title}
            </p>
            <button
              ref={closeButtonRef}
              type="button"
              className={styles.close}
              aria-label={closeLabel}
              onClick={onClose}
            >
              <span aria-hidden="true" className={styles.closeIcon}>
                &times;
              </span>
              Close
            </button>
          </div>
          <div className={styles.body}>{children}</div>
        </div>
      )}
    </dialog>
  )
}
