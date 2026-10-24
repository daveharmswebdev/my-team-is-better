import { useId, useRef } from 'react'
import type { ReactNode } from 'react'
import { ModalDialog } from '../ModalDialog/ModalDialog'
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
 * The full-screen verdict modal (issue #198). A shared link's verdict used to
 * render below the whole form, off-screen on a phone. It now opens over the
 * form, in `ModalDialog`: a native `<dialog>` opened with `showModal()`, in
 * the top layer over an inert page, with focus kept inside it. Escape, the
 * backdrop and the browser's own close requests each call `onClose` once
 * (see `ModalDialog`); this component adds the layout and the close button.
 *
 * - **Layout.** The `<dialog>` covers the viewport and is the scroll
 *   container. The page behind it can't scroll. On a phone the panel fills the
 *   screen. On a wider screen it is a centered column with a max width. The
 *   header with the close button is sticky, so it stays in view while the
 *   content scrolls. Because the scroll container is viewport-sized, a
 *   rating's popover, which places itself against the viewport, is not
 *   clipped by a smaller box.
 * - **Escape** closes the modal, except when a dialog is open inside it
 *   (#216), such as a rating's panel. That Escape belongs to the inner
 *   dialog, which closes itself.
 * - **Focus** moves to the close button on open. It goes back there whenever
 *   the element holding it disappears, for example a correction pill
 *   replaced by the loading state. Returning focus after close is the
 *   parent's job, since only the parent knows where it should go. It must
 *   happen in an effect (as `HomePage` and `PlayerComparePage` do), which
 *   runs after `ModalDialog` has closed the dialog: until then the page is
 *   inert and a `focus()` call there does nothing (#216).
 */
export function VerdictModal({
  open,
  title,
  closeLabel = 'Close',
  onClose,
  children,
}: VerdictModalProps) {
  const closeButtonRef = useRef<HTMLButtonElement>(null)
  const titleId = useId()

  return (
    <ModalDialog
      open={open}
      onClose={onClose}
      initialFocusRef={closeButtonRef}
      className={styles.dialog}
      aria-labelledby={titleId}
    >
      <div className={styles.panel}>
        <div className={styles.header}>
          {/* Not a heading: it names the dialog (`aria-labelledby`). The
              dialog's content continues the page's outline -- the verdict's
              headings sit one level under the page's h1, at the
              `headingLevel` the page passes (#219) -- so it reads right both
              as part of the page and, with the page inert behind this modal,
              on its own (axe heading-order). */}
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
    </ModalDialog>
  )
}
