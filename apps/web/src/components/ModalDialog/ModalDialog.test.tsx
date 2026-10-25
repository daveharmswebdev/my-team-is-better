import { fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useRef } from 'react'
import type { ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { ModalDialog } from './ModalDialog'

/**
 * jsdom has no top layer or inert page (see `src/test/setup.ts`), so these
 * tests cover what the component decides itself: calling `showModal()`, the
 * Tab trap, which close requests reach `onClose`, and the initial focus. The
 * browser's own part is checked in Storybook.
 */
function Example({
  open = true,
  onClose,
  inner,
}: {
  open?: boolean
  onClose: () => void
  inner?: ReactNode
}) {
  const focusRef = useRef<HTMLButtonElement>(null)
  return (
    <>
      <button type="button">Behind</button>
      <ModalDialog
        open={open}
        onClose={onClose}
        aria-label="Outer"
        initialFocusRef={focusRef}
      >
        <button type="button">First</button>
        <button ref={focusRef} type="button">
          Start here
        </button>
        <button type="button" disabled>
          Disabled
        </button>
        {inner}
        <button type="button">Last</button>
      </ModalDialog>
    </>
  )
}

describe('ModalDialog (issue #216)', () => {
  it('opens a native <dialog> with showModal(), names it, and focuses initialFocusRef', () => {
    const showModal = vi.spyOn(HTMLDialogElement.prototype, 'showModal')
    render(<Example onClose={vi.fn()} />)

    const dialog = screen.getByRole('dialog', { name: 'Outer' })
    expect(dialog.tagName).toBe('DIALOG')
    expect(dialog).toHaveAttribute('open')
    expect(dialog).toHaveAttribute('aria-modal', 'true')
    expect(showModal).toHaveBeenCalledTimes(1)
    expect(screen.getByRole('button', { name: 'Start here' })).toHaveFocus()
    showModal.mockRestore()
  })

  it('renders no dialog and none of its children when closed', () => {
    render(<Example open={false} onClose={vi.fn()} />)

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(screen.queryByText('First')).not.toBeInTheDocument()
  })

  it('wraps Tab from the last focusable to the first, and Shift+Tab back', async () => {
    const user = userEvent.setup()
    render(<Example onClose={vi.fn()} />)
    const last = screen.getByRole('button', { name: 'Last' })
    const first = screen.getByRole('button', { name: 'First' })

    last.focus()
    await user.tab()
    expect(first).toHaveFocus()

    await user.tab({ shift: true })
    expect(last).toHaveFocus()
  })

  it('calls onClose exactly once per Escape, and for the cancel event', async () => {
    const user = userEvent.setup()
    const onClose = vi.fn()
    render(<Example onClose={onClose} />)

    await user.keyboard('{Escape}')
    expect(onClose).toHaveBeenCalledTimes(1)

    const cancel = new Event('cancel', { cancelable: true })
    screen.getByRole('dialog').dispatchEvent(cancel)
    expect(onClose).toHaveBeenCalledTimes(2)
    // The parent's `open` prop decides; the browser must not close it itself.
    expect(cancel.defaultPrevented).toBe(true)
  })

  it('calls onClose for a click on the backdrop, not for one inside the content', async () => {
    const user = userEvent.setup()
    const onClose = vi.fn()
    render(<Example onClose={onClose} />)

    await user.click(screen.getByRole('button', { name: 'First' }))
    expect(onClose).not.toHaveBeenCalled()

    await user.click(screen.getByRole('dialog'))
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('calls onClose if the browser closes it on its own, not when the parent does', () => {
    const onClose = vi.fn()
    const { rerender } = render(<Example onClose={onClose} />)

    screen.getByRole<HTMLDialogElement>('dialog').close()
    expect(onClose).toHaveBeenCalledTimes(1)

    rerender(<Example open={false} onClose={onClose} />)
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('ignores a close event that arrives after it has opened again', () => {
    // The browser fires `close` in a later task. A quick close-then-reopen
    // means that stale event lands on a dialog that is open again.
    const onClose = vi.fn()
    render(<Example onClose={onClose} />)

    screen.getByRole('dialog').dispatchEvent(new Event('close'))

    expect(onClose).not.toHaveBeenCalled()
  })

  it('focuses returnFocusRef once the parent has closed it', () => {
    function WithReturn({ open }: { open: boolean }) {
      const returnRef = useRef<HTMLButtonElement>(null)
      return (
        <>
          <button ref={returnRef} type="button">
            Opener
          </button>
          <ModalDialog
            open={open}
            onClose={vi.fn()}
            aria-label="Returns"
            returnFocusRef={returnRef}
          >
            <button type="button">Inside</button>
          </ModalDialog>
        </>
      )
    }
    const close = vi.spyOn(HTMLDialogElement.prototype, 'close')
    const { rerender } = render(<WithReturn open />)
    const opener = screen.getByRole('button', { name: 'Opener' })
    const focus = vi.spyOn(opener, 'focus')

    rerender(<WithReturn open={false} />)

    expect(opener).toHaveFocus()
    expect(focus).toHaveBeenCalledTimes(1)
    // After the dialog closed, never before: an open modal's page is inert.
    expect(close.mock.invocationCallOrder[0]).toBeLessThan(
      focus.mock.invocationCallOrder[0] ?? 0,
    )
    close.mockRestore()
  })

  describe('with a modal dialog open inside it', () => {
    function renderNested() {
      const outerClose = vi.fn()
      const innerClose = vi.fn()
      render(
        <Example
          onClose={outerClose}
          inner={
            <ModalDialog open onClose={innerClose} aria-label="Inner">
              <button type="button">Inner first</button>
              <button type="button">Inner last</button>
            </ModalDialog>
          }
        />,
      )
      const inner = screen.getByRole('dialog', { name: 'Inner' })
      return { outerClose, innerClose, inner }
    }

    it('leaves Escape to the inner dialog', async () => {
      const user = userEvent.setup()
      const { outerClose, innerClose, inner } = renderNested()
      within(inner).getByRole('button', { name: 'Inner first' }).focus()

      await user.keyboard('{Escape}')

      expect(innerClose).toHaveBeenCalledTimes(1)
      expect(outerClose).not.toHaveBeenCalled()
    })

    it("does not hear the inner dialog's close or cancel events", () => {
      const { outerClose, innerClose, inner } = renderNested()

      inner.dispatchEvent(new Event('cancel', { cancelable: true }))
      expect(innerClose).toHaveBeenCalledTimes(1)
      ;(inner as HTMLDialogElement).close()
      expect(innerClose).toHaveBeenCalledTimes(2)

      expect(outerClose).not.toHaveBeenCalled()
    })

    it('does not hear a click on the inner backdrop as its own', () => {
      const { outerClose, innerClose, inner } = renderNested()

      fireEvent.click(inner)

      expect(innerClose).toHaveBeenCalledTimes(1)
      expect(outerClose).not.toHaveBeenCalled()
    })

    it("keeps Tab inside the inner dialog, clear of the outer one's trap", async () => {
      const user = userEvent.setup()
      const { inner } = renderNested()
      const innerFirst = within(inner).getByRole('button', {
        name: 'Inner first',
      })
      const innerLast = within(inner).getByRole('button', {
        name: 'Inner last',
      })

      innerLast.focus()
      await user.tab()
      expect(innerFirst).toHaveFocus()
      await user.tab({ shift: true })
      expect(innerLast).toHaveFocus()
    })
  })
})
