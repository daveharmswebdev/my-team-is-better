import { useEffect, useRef } from 'react'
import type {
  KeyboardEvent,
  MouseEvent,
  ReactNode,
  RefObject,
  SyntheticEvent,
} from 'react'

export interface ModalDialogProps {
  /** Whether the dialog is showing. The parent owns this; the dialog never closes itself. */
  open: boolean
  /**
   * Called once for every request to close: Escape, a click on the backdrop
   * (the `<dialog>` itself, around its content), or the browser's own close
   * request (a back gesture).
   */
  onClose: () => void
  /** Rendered only while open. */
  children: ReactNode
  /**
   * Where focus goes on open, and again whenever the element holding focus
   * disappears. Without it, the browser's `showModal()` default applies.
   */
  initialFocusRef?: RefObject<HTMLElement | null>
  /**
   * Where focus goes when the parent closes the dialog, right after
   * `close()`. It can't be done any earlier: while the dialog is open,
   * everything outside it is inert, so a `focus()` call there does nothing.
   * Without it, the browser restores focus to whatever held it before
   * `showModal()`, which may be nothing (a tap on Safari/iOS doesn't focus
   * the button tapped). A parent that restores focus itself must do it in
   * an effect, which runs after this component's.
   */
  returnFocusRef?: RefObject<HTMLElement | null>
  className?: string
  id?: string
  'aria-label'?: string
  'aria-labelledby'?: string
}

/**
 * A dialog open inside this one: a nested `ModalDialog` (an open `<dialog>`),
 * or a rating's desktop popover, which renders `role="dialog"` only while open.
 */
const NESTED_DIALOG_SELECTOR = 'dialog[open], [role="dialog"]'

const FOCUSABLE_SELECTOR = [
  'a[href]',
  'area[href]',
  'button:not([disabled])',
  'input:not([disabled]):not([type="hidden"])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  'iframe',
  'summary',
  '[tabindex]',
  '[contenteditable="true"]',
].join(', ')

/**
 * The elements Tab reaches inside `dialog`, in order, leaving out those of a
 * dialog nested in it (they belong to that dialog's own trap). Visibility is
 * checked where the browser can (`checkVisibility`); jsdom has no layout.
 */
function tabbablesIn(dialog: HTMLDialogElement): HTMLElement[] {
  return Array.from(
    dialog.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR),
  ).filter(
    (element) =>
      element.tabIndex >= 0 &&
      element.closest('dialog') === dialog &&
      element.closest('[inert]') === null &&
      (typeof element.checkVisibility !== 'function' ||
        element.checkVisibility()),
  )
}

/**
 * The shared modal primitive (issues #198, #216): a native `<dialog>` opened
 * with `showModal()`. The browser puts it in the top layer and makes the rest
 * of the page inert, so nothing behind it can be focused, clicked or read by
 * assistive technology. One may open inside another (a rating's panel inside
 * the verdict); the top layer stacks them.
 *
 * It is controlled: `open` decides, and every close request goes to
 * `onClose`, exactly once.
 *
 * - **Escape** calls `onClose`, except when a dialog is open inside this one.
 *   That Escape belongs to the inner dialog. Which case applies is recorded
 *   in the capture phase, before the inner dialog closes and leaves the DOM.
 *   The keydown is canceled, so the browser doesn't also fire `cancel`.
 * - **Tab** wraps from the last focusable to the first, and Shift+Tab back.
 *   The inert page already keeps focus off it, but a browser may still move
 *   focus to its own UI past the last element. A nested dialog wraps its own.
 * - **Events from a nested dialog** -- React propagates `close` and `cancel`
 *   up the component tree even though the DOM events don't bubble, and a
 *   click on the inner backdrop bubbles -- are ignored here.
 * - **Focus** goes to `initialFocusRef` on open, and back there whenever the
 *   element holding it disappears. On close it goes to `returnFocusRef`,
 *   once the dialog is closed and the page is no longer inert. Without one,
 *   returning focus is the parent's job, in an effect.
 */
export function ModalDialog({
  open,
  onClose,
  children,
  initialFocusRef,
  returnFocusRef,
  className,
  id,
  'aria-label': ariaLabel,
  'aria-labelledby': ariaLabelledBy,
}: ModalDialogProps) {
  const dialogRef = useRef<HTMLDialogElement>(null)
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
      returnFocusRef?.current?.focus()
    }
    // A ref object is stable, and a rerun with `open` unchanged does nothing.
  }, [open, returnFocusRef])

  // Runs after every render. While open, focus belongs inside. If it isn't
  // there (just opened, or its element was replaced), put it back.
  useEffect(() => {
    const dialog = dialogRef.current
    if (open && dialog !== null && !dialog.contains(document.activeElement)) {
      initialFocusRef?.current?.focus()
    }
  })

  useEffect(() => {
    if (!open) {
      return
    }
    function recordEscapeTarget(event: globalThis.KeyboardEvent) {
      if (event.key === 'Escape') {
        escapeIsForNestedDialogRef.current =
          dialogRef.current?.querySelector(NESTED_DIALOG_SELECTOR) != null
      }
    }
    function handleEscape(event: globalThis.KeyboardEvent) {
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
    if (event.target !== event.currentTarget) {
      return
    }
    event.preventDefault()
    onClose()
  }

  /**
   * The dialog closed without the parent asking, which a browser can do
   * without a `cancel` event. The parent hears about it, so its state and the
   * page agree again. The event comes in a later task, so after a quick
   * close and reopen it can arrive stale, on a dialog that is open again:
   * that one is ignored.
   */
  function handleNativeClose(event: SyntheticEvent<HTMLDialogElement>) {
    if (
      event.target === event.currentTarget &&
      !event.currentTarget.open &&
      openRef.current
    ) {
      onCloseRef.current()
    }
  }

  /** A click on the dimmed area around the content, which is the dialog itself. */
  function handleClick(event: MouseEvent<HTMLDialogElement>) {
    if (event.target === event.currentTarget) {
      onClose()
    }
  }

  function handleKeyDown(event: KeyboardEvent<HTMLDialogElement>) {
    const dialog = event.currentTarget
    if (
      event.key !== 'Tab' ||
      event.defaultPrevented ||
      !(event.target instanceof Element) ||
      event.target.closest('dialog') !== dialog
    ) {
      return
    }
    const tabbables = tabbablesIn(dialog)
    const first = tabbables.at(0)
    const last = tabbables.at(-1)
    if (first === undefined || last === undefined) {
      event.preventDefault()
      return
    }
    const active = document.activeElement
    // Focus on the dialog itself (or nowhere) is before the first element.
    const outside = active === dialog || !dialog.contains(active)
    if (event.shiftKey && (active === first || outside)) {
      event.preventDefault()
      last.focus()
    } else if (!event.shiftKey && (active === last || outside)) {
      event.preventDefault()
      first.focus()
    }
  }

  return (
    // The backdrop click is only a pointer shortcut for Escape, which is the
    // keyboard way to do the same thing.
    <dialog
      ref={dialogRef}
      id={id}
      className={className}
      aria-label={ariaLabel}
      aria-labelledby={ariaLabelledBy}
      // Implied by `showModal()`; stated for assistive technology that
      // doesn't derive it.
      aria-modal="true"
      onCancel={handleCancel}
      onClose={handleNativeClose}
      onClick={handleClick}
      onKeyDown={handleKeyDown}
    >
      {open && children}
    </dialog>
  )
}
